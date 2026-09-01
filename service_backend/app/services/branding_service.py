"""Branding service (plan sprint-2/03) - business rules behind both route sets
(tenant /branding and operator /platform/tenants/{id}/branding).

Token documents validate against the canonical whitelist (named 422 errors,
default-equal values normalize away). Assets validate type + size + content
sniff, store via the core StorageService, and bump ``version`` - public URLs
carry ``?v=`` so long-cached assets/CSS never go stale.
"""
import logging
from typing import Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.branding.token_whitelist import build_template, tokens_to_css, validate_tokens
from app.config import settings
from app.models.tenant import Tenant
from app.models.tenant_branding import TenantBranding
from app.repositories.branding_repository import BrandingRepository
from app.services.storage import UnresolvableKey, storage_for_tenant

logger = logging.getLogger(__name__)


class BrandingError(Exception):
    """422 - invalid tokens / asset. ``errors`` lists every named problem."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


class PlatformTenantBrandingRejected(Exception):
    """409 - the platform console keeps stock branding (plan 03 D10)."""


class TenantNotFound(Exception):
    pass


ASSET_KINDS = ("logo", "favicon", "illustration")

# Client-side mirror lives in components/platform/branding/asset-upload-card.
# Favicon accepts JPEG/WebP too - modern browsers render any image format as
# a tab icon; the square-PNG/ICO advice stays a hint, not a gate.
ASSET_RULES: Dict[str, Tuple[Tuple[str, ...], int]] = {
    "logo": (("image/png", "image/jpeg", "image/svg+xml", "image/webp"), 2 * 1024 * 1024),
    "illustration": (
        ("image/png", "image/jpeg", "image/svg+xml", "image/webp"),
        2 * 1024 * 1024,
    ),
    "favicon": (
        ("image/png", "image/jpeg", "image/webp", "image/x-icon", "image/vnd.microsoft.icon"),
        512 * 1024,
    ),
}

# Content sniffing - shared gate since plan 06 (avatars need it too); see
# app/uploads.py for the rationale (declared type = client input, lies).
from app.uploads import detect_mime as _detect_mime  # noqa: E402


class BrandingService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = BrandingRepository(db)

    # ---- reads ----

    def get(self, tenant_id: str) -> dict:
        row = self.repo.get_by_tenant(tenant_id)
        return self._to_response(row)

    def get_checked(self, tenant_id: str) -> dict:
        """Operator read - 404 unknown tenant instead of silently-empty 200
        (review finding: reads and writes must share one existence contract).
        The platform tenant IS readable (the console shows its stock-branding
        notice); only writes reject it."""
        self._ensure_tenant(tenant_id)
        return self.get(tenant_id)

    def template(self, tenant_id: str) -> dict:
        row = self.repo.get_by_tenant(tenant_id)
        return build_template(row.tokens_json if row else None)

    def template_checked(self, tenant_id: str) -> dict:
        self._ensure_tenant(tenant_id)
        return self.template(tenant_id)

    def public(self, slug: str) -> dict:
        """Branding for a host slug. Unknown slug OR unbranded tenant return
        the SAME zeroed document - no tenant-enumeration signal (plan 03)."""
        row = self.repo.get_by_slug(slug)
        if row is None or not self._is_branded(row):
            return PUBLIC_DEFAULTS.copy()
        return {
            "isBranded": True,
            "tenantName": row.tenant.name,
            "appName": row.app_name,
            "slogan": row.slogan,
            **self._asset_urls(row),
            "tokens": row.tokens_json,
            "version": row.version,
        }

    def theme_css(self, slug: str) -> Tuple[str, int]:
        """Generated override CSS + version (ETag seed). Unbranded = empty 200."""
        row = self.repo.get_by_slug(slug)
        if row is None:
            return "", 0
        return tokens_to_css(row.tokens_json), row.version

    def resolve_asset(self, slug: str, kind: str) -> Optional[Tuple[str, str, str, str]]:
        """(location, value, mime, disposition) for the public asset route -
        the storage resolution lives HERE because the key's backend is the
        owning tenant's connection chain (plan 06 D1)."""
        if kind not in ASSET_KINDS:
            return None
        row = self.repo.get_by_slug(slug)
        if row is None:
            return None
        key = getattr(row, f"{kind}_key")
        mime = getattr(row, f"{kind}_mime")
        if not key:
            return None
        try:
            location, value = storage_for_tenant(self.db, row.tenant_id).resolve(key)
        except UnresolvableKey:
            logger.warning("branding asset key %s unresolvable (connection gone)", key)
            return None
        return location, value, mime or "application/octet-stream", "inline"

    # ---- writes (routes resolve the tenant; platform tenant rejected) ----

    # Whitelisted social/footer keys (plan 07 D4) - unknown keys 422 loudly.
    SOCIAL_KEYS = ("facebook", "instagram", "x", "linkedin", "youtube", "tiktok", "website")
    FOOTER_KEYS = ("companyName", "addressLine", "tagline")

    @classmethod
    def _clean_keyed(cls, doc: Optional[dict], allowed, label: str) -> Optional[dict]:
        if doc is None:
            return None
        unknown = [k for k in doc if k not in allowed]
        if unknown:
            raise BrandingError([f'Unknown {label} field "{unknown[0]}".'])
        cleaned = {k: (v.strip() if isinstance(v, str) and v.strip() else None) for k, v in doc.items()}
        return cleaned if any(cleaned.values()) else None

    def update(
        self,
        tenant_id: str,
        slogan: Optional[str],
        tokens: Optional[dict],
        socials: Optional[dict] = None,
        footer: Optional[dict] = None,
        app_name: Optional[str] = None,
    ) -> dict:
        self._guard_tenant(tenant_id)
        validated = None
        if tokens is not None:
            validated, errors = validate_tokens(tokens)
            if errors:
                raise BrandingError(errors)
        row = self.repo.get_or_create(tenant_id)
        row.slogan = slogan.strip() if slogan and slogan.strip() else None
        row.app_name = app_name.strip() if app_name and app_name.strip() else None
        row.tokens_json = validated
        # Socials/footer: omitted (None) = untouched; sent = replace (the
        # frontend always sends the full objects from its draft).
        if socials is not None:
            row.socials_json = self._clean_keyed(socials, self.SOCIAL_KEYS, "social")
        if footer is not None:
            row.footer_json = self._clean_keyed(footer, self.FOOTER_KEYS, "footer")
        row.version += 1
        self.db.commit()
        self.db.refresh(row)
        return self._to_response(row)

    def upload_asset(self, tenant_id: str, kind: str, content: bytes,
                     mime: str, filename: str) -> dict:
        self._guard_tenant(tenant_id)
        if kind not in ASSET_KINDS:
            raise BrandingError([f'Unknown asset kind "{kind}".'])
        accept, max_bytes = ASSET_RULES[kind]
        if len(content) > max_bytes:
            raise BrandingError(
                [f"File too large - max {max_bytes // 1024} KB for {kind}."]
            )
        # Trust the sniffed type, never the declared one - extensions lie
        # (a JPEG renamed .png arrives declared image/png). Detected-and-allowed
        # is accepted with the corrected mime stored.
        detected = _detect_mime(content)
        if detected is None:
            raise BrandingError(
                ["Unrecognized image format - use PNG, JPG, SVG, WebP or ICO."]
            )
        if detected not in accept:
            raise BrandingError(
                [f"Unsupported file type for {kind} (file is {detected})."]
            )

        row = self.repo.get_or_create(tenant_id)
        old_key = getattr(row, f"{kind}_key")
        # Connection-driven storage (plan 06 D1): tenant bucket → platform →
        # local disk; the key carries its writing backend.
        new_key = storage_for_tenant(self.db, tenant_id).save(
            f"branding/{tenant_id}/{kind}", content, detected
        )
        setattr(row, f"{kind}_key", new_key)
        setattr(row, f"{kind}_mime", detected)
        row.version += 1
        self.db.commit()
        self._delete_blob(tenant_id, old_key)  # after commit - never orphan the row
        self.db.refresh(row)
        return self._to_response(row)

    def remove_asset(self, tenant_id: str, kind: str) -> dict:
        self._guard_tenant(tenant_id)
        if kind not in ASSET_KINDS:
            raise BrandingError([f'Unknown asset kind "{kind}".'])
        row = self.repo.get_or_create(tenant_id)
        old_key = getattr(row, f"{kind}_key")
        setattr(row, f"{kind}_key", None)
        setattr(row, f"{kind}_mime", None)
        row.version += 1
        self.db.commit()
        self._delete_blob(tenant_id, old_key)
        self.db.refresh(row)
        return self._to_response(row)

    # ---- internals ----

    def _delete_blob(self, tenant_id: str, key: Optional[str]) -> None:
        """Best-effort cleanup AFTER a successful commit - a storage hiccup
        must not 500 a write that already succeeded (review finding). The
        orphaned blob is the lesser evil; log and move on."""
        if not key:
            return
        try:
            storage_for_tenant(self.db, tenant_id).delete(key)
        except Exception:  # noqa: BLE001 - deliberate best-effort
            logger.warning("branding: failed to delete replaced blob %s", key)

    def _ensure_tenant(self, tenant_id: str) -> Tenant:
        tenant = self.db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if tenant is None:
            raise TenantNotFound()
        return tenant

    def _guard_tenant(self, tenant_id: str) -> Tenant:
        tenant = self._ensure_tenant(tenant_id)
        if tenant.is_platform:
            raise PlatformTenantBrandingRejected()
        return tenant

    @staticmethod
    def _is_branded(row: TenantBranding) -> bool:
        return bool(
            row.slogan
            or row.app_name
            or row.logo_key
            or row.favicon_key
            or row.illustration_key
            or row.tokens_json
        )

    def _asset_urls(self, row: TenantBranding) -> dict:
        slug = row.tenant.slug
        base = f"{settings.public_base_url}/public/branding/{slug}/asset"

        def url(kind: str) -> Optional[str]:
            return (
                f"{base}/{kind}?v={row.version}"
                if getattr(row, f"{kind}_key")
                else None
            )

        return {
            "logoUrl": url("logo"),
            "faviconUrl": url("favicon"),
            "illustrationUrl": url("illustration"),
        }

    def _to_response(self, row: Optional[TenantBranding]) -> dict:
        if row is None:
            return {
                "slogan": None,
                "appName": None,
                "logoUrl": None,
                "faviconUrl": None,
                "illustrationUrl": None,
                "tokens": None,
                "socials": None,
                "footer": None,
                "version": 0,
            }
        return {
            "slogan": row.slogan,
            "appName": row.app_name,
            **self._asset_urls(row),
            "tokens": row.tokens_json,
            "socials": row.socials_json,
            "footer": row.footer_json,
            "version": row.version,
        }


PUBLIC_DEFAULTS = {
    "isBranded": False,
    "tenantName": None,
    "appName": None,
    "slogan": None,
    "logoUrl": None,
    "faviconUrl": None,
    "illustrationUrl": None,
    "tokens": None,
    "version": 0,
}
