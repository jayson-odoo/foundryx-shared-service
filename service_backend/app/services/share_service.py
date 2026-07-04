"""Document-sharing business logic (plan sprint-3/05, Google-Drive model) —
Router → THIS → ShareRepository/DocumentRepository.

A shared target has ONE stable ``file_shares`` row (token never changes). The
owner edits it in place: ``general_access`` (restricted | workspace | public),
its ``general_capability`` (view | edit), and an additive named-people list
(``file_share_users``, each with its own role). Flipping "Anyone with the link"
→ "Restricted" simply makes the same URL stop resolving for the public.

Access resolution (``_effective_capability``):
  * anonymous  → access only when general_access == public, clamped by the
    tenant ``document_settings.public_sharing`` ceiling; else "sign in to access".
  * authenticated same-tenant → max(role from the people list, role from
    general_access when workspace/public); none ⇒ denied.

Security invariants (never the client): the ceiling is clamped at every public
serve; stored ``user_id``/``file_links`` ids are validated to the share's tenant
at save and tenant-scoped at resolve; public writes ride their own throttle
bucket + honeypot + sniff floor + quota + per-link caps + ``share:{token}`` audit.
"""
import secrets
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.models.document import (
    SHARE_ACCESS_LEVELS,
    SHARE_ACCESS_PUBLIC,
    SHARE_ACCESS_RESTRICTED,
    SHARE_ACCESS_WORKSPACE,
    SHARE_CAP_EDIT,
    SHARE_CAP_VIEW,
    SHARE_CAPABILITIES,
    SHARE_DEFAULT_MAX_TOTAL_MB,
    SHARE_DEFAULT_MAX_UPLOADS,
    SHARE_TARGET_FILE,
    SHARE_TARGET_FOLDER,
    SHARE_TARGET_KINDS,
    SHARING_OFF,
    SHARING_VIEW,
    File,
    FileLink,
    FileShare,
    FileShareUser,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.repositories.share_repository import ShareRepository
from app.schemas.document import (
    FileLinkOut,
    PublicShareFileNode,
    PublicShareFolderNode,
    PublicShareView,
    ShareOut,
    SharePersonInput,
    ShareUpdateRequest,
    ShareUserOut,
)
from app.security import hash_password, verify_password

MB = 1024 * 1024
# The honeypot field name the public upload form renders off-screen (D6).
SHARE_HONEYPOT_FIELD = "company_website"


# ---- service exceptions ----


class ShareNotFound(Exception):
    """Uniform 404 — unknown / disabled token (no enumeration)."""


class ShareForbidden(Exception):
    """Authed caller is not authorized for this share / lacks a mint gate."""

    def __init__(self, message: str = "You don't have access to this link."):
        super().__init__(message)
        self.message = message


class ShareInvalid(Exception):
    """422 — malformed update (bad access level/capability, past expiry, foreign
    allow-list user, missing target)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class SharePasswordInvalid(Exception):
    """Wrong password on unlock/serve/upload — the router pumps the throttle."""


class ShareCapExceeded(Exception):
    """A per-link upload cap (max_uploads / max_total_mb) would be exceeded."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _preview_kind(mime: str) -> str:
    if mime.startswith("image/"):
        return "image"
    if mime == "application/pdf":
        return "pdf"
    return "none"


def _stronger(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """The stronger of two capabilities (edit > view), ignoring None."""
    caps = [c for c in (a, b) if c]
    if not caps:
        return None
    return SHARE_CAP_EDIT if SHARE_CAP_EDIT in caps else SHARE_CAP_VIEW


class ShareService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ShareRepository(db)
        self.docs = DocumentRepository(db)
        from app.services.document_service import DocumentService

        self.doc_service = DocumentService(db)

    # ---- policy ----

    def _ceiling(self, tenant_id: str) -> str:
        row = self.docs.get_settings(tenant_id)
        return row.public_sharing if row else SHARING_OFF

    def _public_capability(self, tenant_id: str, capability: str) -> Optional[str]:
        """The effective ANONYMOUS capability under the tenant ceiling, or None
        when the ceiling blocks public access entirely (D5)."""
        ceiling = self._ceiling(tenant_id)
        if ceiling == SHARING_OFF:
            return None
        if ceiling == SHARING_VIEW and capability == SHARE_CAP_EDIT:
            return SHARE_CAP_VIEW
        return capability

    # ---- builders ----

    def _user_name(self, tenant_id: str, user_id: Optional[str]) -> Optional[str]:
        if not user_id:
            return None
        u = (
            self.db.query(User)
            .filter(User.id == user_id, User.tenant_id == tenant_id)
            .first()
        )
        return (u.name or u.email) if u else None

    def _target_name(self, share: FileShare) -> Optional[str]:
        if share.target_kind == SHARE_TARGET_FILE:
            f = self.docs.get_file(share.tenant_id, share.target_id)
            return f.name if f else None
        folder = self.docs.get_folder(share.tenant_id, share.target_id)
        return folder.name if folder else None

    def _is_expired(self, share: FileShare) -> bool:
        return share.expires_at is not None and share.expires_at <= _now()

    def _share_url(self, token: str) -> str:
        base = settings.public_base_url.rstrip("/")
        return f"{base}/public/documents/{token}"

    def _share_out(self, share: FileShare) -> ShareOut:
        people: List[ShareUserOut] = []
        for su in self.repo.share_users(share.id):
            u = (
                self.db.query(User)
                .filter(User.id == su.user_id, User.tenant_id == share.tenant_id)
                .first()
            )
            if u:
                people.append(
                    ShareUserOut(
                        id=u.id, name=u.name, email=u.email, capability=su.capability
                    )
                )
        return ShareOut(
            id=share.id,
            target_kind=share.target_kind,
            target_id=share.target_id,
            target_name=self._target_name(share),
            general_access=share.general_access,
            capability=share.general_capability,
            token=share.token,
            url=self._share_url(share.token),
            expires_at=share.expires_at,
            is_expired=self._is_expired(share),
            has_password=share.password_hash is not None,
            max_uploads=share.max_uploads,
            max_total_mb=share.max_total_mb,
            is_disabled=share.is_disabled,
            people=people,
            created_by=share.created_by,
            created_by_name=self._user_name(share.tenant_id, share.created_by),
            created_at=share.created_at,
        )

    # ---- ensure / update / list / revoke ----

    def ensure(
        self, tenant_id: str, actor: User, target_kind: str, target_id: str
    ) -> ShareOut:
        """Get-or-create the ONE stable share for a target (opening the dialog).
        Created Restricted/View by default — like Google, the link exists
        immediately but only the owner (and named people) can use it."""
        if target_kind not in SHARE_TARGET_KINDS:
            raise ShareInvalid("Invalid share target.")
        if target_kind == SHARE_TARGET_FILE:
            target = self.docs.get_file(tenant_id, target_id)
        else:
            target = self.docs.get_folder(tenant_id, target_id)
        if target is None or target.is_deleted:
            raise ShareInvalid("Target not found.")

        existing = self.repo.for_target(tenant_id, target_kind, target_id)
        if existing:
            share = existing[0]
            if share.is_disabled:  # re-enable on re-open (Google re-creates the link)
                share.is_disabled = False
                self.db.commit()
            return self._share_out(share)

        share = FileShare(
            tenant_id=tenant_id,
            target_kind=target_kind,
            target_id=target_id,
            token=secrets.token_urlsafe(32),
            general_access=SHARE_ACCESS_RESTRICTED,
            general_capability=SHARE_CAP_VIEW,
            created_by=actor.id,
        )
        self.repo.add(share)
        self.db.commit()
        self.db.refresh(share)
        return self._share_out(share)

    def update(
        self, tenant_id: str, share_id: str, can_manage: bool, req: ShareUpdateRequest
    ) -> ShareOut:
        share = self.repo.get(tenant_id, share_id)
        if share is None:
            raise ShareNotFound()
        fields = req.model_fields_set

        new_access = req.generalAccess if req.generalAccess is not None else share.general_access
        new_cap = req.capability if req.capability is not None else share.general_capability
        if new_access not in SHARE_ACCESS_LEVELS:
            raise ShareInvalid("Invalid access level.")
        if new_cap not in SHARE_CAPABILITIES:
            raise ShareInvalid("Invalid capability.")

        # Public-access ceiling + manage gates (server-side, never trust client).
        if new_access == SHARE_ACCESS_PUBLIC:
            ceiling = self._ceiling(tenant_id)
            if ceiling == SHARING_OFF:
                raise ShareForbidden("Public sharing is turned off for this workspace.")
            if ceiling == SHARING_VIEW and new_cap == SHARE_CAP_EDIT:
                raise ShareForbidden("Public links can only be view-only here.")
            if new_cap == SHARE_CAP_EDIT and not can_manage:
                raise ShareForbidden(
                    "Public edit links require the Manage documents permission."
                )
        share.general_access = new_access
        share.general_capability = new_cap

        if "expiresAt" in fields:
            exp = req.expiresAt
            if exp is not None:
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp <= _now():
                    raise ShareInvalid("Expiry must be a future date.")
            share.expires_at = exp
        if "password" in fields:
            share.password_hash = hash_password(req.password) if req.password else None
        if "maxUploads" in fields:
            share.max_uploads = req.maxUploads
        if "maxTotalMb" in fields:
            share.max_total_mb = req.maxTotalMb
        if req.isDisabled is not None:
            share.is_disabled = req.isDisabled

        if req.people is not None:
            self._replace_people(tenant_id, share, req.people)

        self.db.commit()
        self.db.refresh(share)
        return self._share_out(share)

    def _replace_people(
        self, tenant_id: str, share: FileShare, people: List[SharePersonInput]
    ) -> None:
        # Validate every id to THIS tenant (cross-tenant-leak rule).
        seen: Dict[str, str] = {}
        for p in people:
            if p.capability not in SHARE_CAPABILITIES:
                raise ShareInvalid("Invalid person capability.")
            u = (
                self.db.query(User)
                .filter(User.id == p.userId, User.tenant_id == tenant_id)
                .first()
            )
            if u is None:
                raise ShareInvalid("A person is not in this workspace.")
            seen[p.userId] = p.capability
        for existing in self.repo.share_users(share.id):
            self.db.delete(existing)
        self.db.flush()
        for uid, cap in seen.items():
            self.repo.add_share_user(
                FileShareUser(share_id=share.id, user_id=uid, capability=cap)
            )

    def list_target(
        self, tenant_id: str, target_kind: str, target_id: str
    ) -> Optional[ShareOut]:
        rows = self.repo.for_target(tenant_id, target_kind, target_id)
        active = [r for r in rows if not r.is_disabled]
        return self._share_out(active[0]) if active else None

    def list_shares(
        self,
        tenant_id: str,
        *,
        page: int,
        page_size: int,
        search: Optional[str],
        sort_by: Optional[str],
        sort_dir: str,
        disabled: bool,
    ) -> Tuple[List[ShareOut], int]:
        rows, total = self.repo.paginate(
            tenant_id, page=page, page_size=page_size, search=search,
            sort_by=sort_by, sort_dir=sort_dir, disabled=disabled,
        )
        return [self._share_out(s) for s in rows], total

    def revoke(self, tenant_id: str, share_ids: List[str]) -> None:
        for sid in share_ids:
            share = self.repo.get(tenant_id, sid)
            if share and not share.is_disabled:
                share.is_disabled = True
        self.db.commit()

    def list_shared_with_me(self, tenant_id: str, user: User):
        """Roots shared TO this user by OTHERS — the "Shared with me" drive.
        Excludes the user's own shares (those live under their Drive) and any
        link they can't actually open."""
        from app.schemas.document import SharedWithMeItem

        out: List[SharedWithMeItem] = []
        for s in self.repo.active_in_tenant(tenant_id):
            if s.created_by == user.id or self._is_expired(s):
                continue
            cap = self._effective_capability(s, user)
            if cap is None:
                continue
            name = self._target_name(s)
            if name is None:  # target gone
                continue
            out.append(
                SharedWithMeItem(
                    token=s.token,
                    target_kind=s.target_kind,
                    target_id=s.target_id,
                    name=name,
                    capability=cap,
                    owner_name=self._user_name(tenant_id, s.created_by),
                    shared_at=s.created_at,
                )
            )
        return out

    def list_tenant_users(
        self, tenant_id: str, search: Optional[str], limit: int = 50
    ) -> List[ShareUserOut]:
        from sqlalchemy import or_

        from app.models.user import UserStatus

        q = self.db.query(User).filter(
            User.tenant_id == tenant_id, User.status == UserStatus.ACTIVE.value
        )
        if search:
            like = f"%{search}%"
            q = q.filter(or_(User.name.ilike(like), User.email.ilike(like)))
        rows = q.order_by(User.name).limit(limit).all()
        return [ShareUserOut(id=u.id, name=u.name, email=u.email) for u in rows]

    # ---- access resolution ----

    def _people_caps(self, share: FileShare) -> Dict[str, str]:
        return {su.user_id: su.capability for su in self.repo.share_users(share.id)}

    def _effective_capability(
        self, share: FileShare, user: Optional[User]
    ) -> Optional[str]:
        """The caller's effective role on the share, or None if denied. Anonymous
        access only via general_access=public (clamped by the ceiling); a tenant
        member takes the stronger of their named role and the general role."""
        if user is None:
            if share.general_access != SHARE_ACCESS_PUBLIC:
                return None
            return self._public_capability(share.tenant_id, share.general_capability)
        if user.tenant_id != share.tenant_id:
            return None
        general_cap = (
            share.general_capability
            if share.general_access in (SHARE_ACCESS_WORKSPACE, SHARE_ACCESS_PUBLIC)
            else None
        )
        person_cap = self._people_caps(share).get(user.id)
        return _stronger(general_cap, person_cap)

    # ---- reachability (folder live-follow ancestry walk, D4) ----

    def _reachable_file(self, share: FileShare, file: File) -> bool:
        if file is None or file.is_deleted:
            return False
        if share.target_kind == SHARE_TARGET_FILE:
            return file.id == share.target_id
        return self._folder_in_subtree(share.tenant_id, share.target_id, file.folder_id)

    def _folder_in_subtree(
        self, tenant_id: str, root_id: str, folder_id: Optional[str]
    ) -> bool:
        seen: set = set()
        cur_id = folder_id
        while cur_id is not None and cur_id not in seen:
            seen.add(cur_id)
            cur = self.docs.get_folder(tenant_id, cur_id)
            if cur is None or cur.is_deleted:
                return False
            if cur.id == root_id:
                return True
            cur_id = cur.parent_id
        return False

    # ---- resolve (state envelope) ----

    def resolve(
        self,
        token: str,
        *,
        user: Optional[User],
        public_route: bool,
        folder_id: Optional[str] = None,
        password_ok: bool = False,
    ) -> PublicShareView:
        share = self.repo.get_by_token(token)
        if share is None or share.is_disabled:
            raise ShareNotFound()

        if self._is_expired(share):
            return PublicShareView(
                state="closed",
                tenant_name=self._tenant_name(share.tenant_id),
                message="This link has expired.",
            )

        cap = self._effective_capability(share, user)
        if cap is None:
            if public_route:
                # Anonymous + not-public (or ceiling-blocked) → "sign in to
                # access" (decision: route real members to auth, not a blank 404).
                return PublicShareView(
                    state="sign_in_required",
                    tenant_name=self._tenant_name(share.tenant_id),
                )
            raise ShareForbidden()  # authed but not authorized

        if share.password_hash is not None and not password_ok:
            return PublicShareView(
                state="password_required",
                tenant_name=self._tenant_name(share.tenant_id),
            )

        return self._open_view(share, folder_id, cap)

    def _tenant_name(self, tenant_id: str) -> Optional[str]:
        t = self.db.query(Tenant).filter(Tenant.id == tenant_id).first()
        return t.name if t else None

    def _file_node(self, file: File) -> Optional[PublicShareFileNode]:
        current = self.docs.current_version(file)
        if current is None:
            return None
        return PublicShareFileNode(
            id=file.id,
            name=file.name,
            mime=current.mime,
            size_bytes=current.size_bytes,
            preview_kind=_preview_kind(current.mime),
        )

    def _open_view(
        self, share: FileShare, folder_id: Optional[str], capability: str
    ) -> PublicShareView:
        tenant_name = self._tenant_name(share.tenant_id)
        honeypot = SHARE_HONEYPOT_FIELD if capability == SHARE_CAP_EDIT else None
        if share.target_kind == SHARE_TARGET_FILE:
            file = self.docs.get_file(share.tenant_id, share.target_id)
            if file is None or file.is_deleted:
                raise ShareNotFound()
            node = self._file_node(file)
            if node is None:
                raise ShareNotFound()
            return PublicShareView(
                state="open",
                tenant_name=tenant_name,
                kind="file",
                capability=capability,
                title=file.name,
                file=node,
                honeypot_field=honeypot,
            )

        root = self.docs.get_folder(share.tenant_id, share.target_id)
        if root is None or root.is_deleted:
            raise ShareNotFound()
        listing_id = folder_id or share.target_id
        if listing_id != share.target_id and not self._folder_in_subtree(
            share.tenant_id, share.target_id, listing_id
        ):
            raise ShareNotFound()
        listing_folder = self.docs.get_folder(share.tenant_id, listing_id)
        if listing_folder is None or listing_folder.is_deleted:
            raise ShareNotFound()

        crumbs: List[PublicShareFolderNode] = []
        chain = self.docs.breadcrumb(share.tenant_id, listing_id)
        started = False
        for f in chain:
            if f.id == share.target_id:
                started = True
            if started:
                crumbs.append(PublicShareFolderNode(id=f.id, name=f.name))

        sub_folders = [
            PublicShareFolderNode(id=f.id, name=f.name)
            for f in self.docs.child_folders(share.tenant_id, listing_id)
        ]
        sub_files: List[PublicShareFileNode] = []
        for f in self.docs.child_files(share.tenant_id, listing_id):
            node = self._file_node(f)
            if node is not None:
                sub_files.append(node)

        return PublicShareView(
            state="open",
            tenant_name=tenant_name,
            kind="folder",
            capability=capability,
            title=root.name,
            folder_id=listing_id,
            breadcrumb=crumbs,
            folders=sub_folders,
            files=sub_files,
            honeypot_field=honeypot,
        )

    # ---- unlock ----

    def verify_unlock(self, token: str, password: str) -> bool:
        share = self.repo.get_by_token(token)
        if share is None or share.is_disabled or self._is_expired(share):
            return False
        if share.password_hash is None:
            return True
        return verify_password(password, share.password_hash)

    # ---- share-scoped serving ----

    def serve_file(
        self,
        token: str,
        file_id: str,
        *,
        user: Optional[User],
        public_route: bool,
        password: Optional[str],
    ) -> Tuple[str, str, str]:
        share = self.repo.get_by_token(token)
        if share is None or share.is_disabled or self._is_expired(share):
            raise ShareNotFound()
        cap = self._effective_capability(share, user)
        if cap is None:
            raise ShareNotFound() if public_route else ShareForbidden()
        if share.password_hash is not None:
            if not password or not verify_password(password, share.password_hash):
                raise SharePasswordInvalid()
        file = self.docs.get_file(share.tenant_id, file_id)
        if file is None or not self._reachable_file(share, file):
            raise ShareNotFound()
        current = self.docs.current_version(file)
        if current is None:
            raise ShareNotFound()
        return current.storage_key, current.mime, file.name

    def tenant_for_token(self, token: str) -> Optional[str]:
        share = self.repo.get_by_token(token)
        return share.tenant_id if share else None

    # ---- guarded public-edit upload (D6) ----

    def public_upload(
        self,
        token: str,
        filename: str,
        content: bytes,
        *,
        user: Optional[User] = None,
        password: Optional[str],
        folder_id: Optional[str] = None,
    ) -> None:
        share = self.repo.get_by_token(token)
        if share is None or share.is_disabled or self._is_expired(share):
            raise ShareNotFound()
        cap = self._effective_capability(share, user)
        if cap != SHARE_CAP_EDIT:
            raise ShareNotFound() if user is None else ShareForbidden()
        if share.password_hash is not None:
            if not password or not verify_password(password, share.password_hash):
                raise SharePasswordInvalid()

        max_uploads = share.max_uploads or SHARE_DEFAULT_MAX_UPLOADS
        max_total_mb = share.max_total_mb or SHARE_DEFAULT_MAX_TOTAL_MB
        if share.uploads_count + 1 > max_uploads:
            raise ShareCapExceeded("This link has reached its upload limit.")
        if share.uploads_bytes + len(content) > max_total_mb * MB:
            raise ShareCapExceeded("This link has reached its total-size limit.")

        if share.target_kind == SHARE_TARGET_FOLDER:
            dest_folder = folder_id or share.target_id
            if dest_folder != share.target_id and not self._folder_in_subtree(
                share.tenant_id, share.target_id, dest_folder
            ):
                raise ShareNotFound()
            dest_name = filename
        else:
            file = self.docs.get_file(share.tenant_id, share.target_id)
            if file is None or file.is_deleted:
                raise ShareNotFound()
            dest_folder = file.folder_id
            dest_name = file.name

        # An authenticated editor's write is attributed to THEM; an anonymous
        # public-edit write to the synthetic share actor (D6).
        self.doc_service.upload(
            share.tenant_id,
            dest_folder,
            dest_name,
            content,
            None,
            "replace",
            user,
            actor_id=None if user else f"share:{token}",
        )
        share.uploads_count += 1
        share.uploads_bytes += len(content)
        self.db.commit()

    # ---- file_links seam (D8, isolation-tested only) ----

    def link_file(
        self, tenant_id: str, entity_type: str, entity_id: str, file_id: str, actor: User
    ) -> FileLinkOut:
        file = self.docs.get_file(tenant_id, file_id)
        if file is None:
            raise ShareInvalid("File not found in this workspace.")
        row = FileLink(
            tenant_id=tenant_id,
            entity_type=entity_type.strip(),
            entity_id=entity_id.strip(),
            file_id=file_id,
            created_by=actor.id,
        )
        self.repo.add_link(row)
        self.db.commit()
        return self._link_out(row)

    def list_links(
        self, tenant_id: str, entity_type: str, entity_id: str
    ) -> List[FileLinkOut]:
        return [
            self._link_out(r)
            for r in self.repo.links_for_entity(tenant_id, entity_type, entity_id)
        ]

    def unlink_file(self, tenant_id: str, link_id: str) -> None:
        row = self.repo.get_link(tenant_id, link_id)
        if row is None:
            raise ShareInvalid("Link not found.")
        self.repo.delete_link(row)
        self.db.commit()

    @staticmethod
    def _link_out(row: FileLink) -> FileLinkOut:
        return FileLinkOut(
            id=row.id,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            file_id=row.file_id,
            created_at=row.created_at,
        )
