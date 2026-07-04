"""User model. Tenant-scoped; roles are many-to-many (plan 02)."""
import enum
import uuid

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base
from app.models.role import user_roles
from app.models.tenant import DEFAULT_TENANT_ID


class UserStatus(str, enum.Enum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    # System-managed: set on invite-create, cleared when the user sets a password.
    INVITED = "INVITED"


class User(Base):
    __tablename__ = "users"
    # Email is unique per tenant, not globally (multi-tenant).
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Tenancy groundwork: every user belongs to a tenant. Defaults to the
    # bootstrap tenant until the full tenancy model lands (BL-004).
    tenant_id = Column(
        String,
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
        default=DEFAULT_TENANT_ID,
    )
    email = Column(String, nullable=False, index=True)
    password = Column(String, nullable=True)  # bcrypt hash; null until set-password
    name = Column(String, nullable=True)
    status = Column(String, default=UserStatus.INACTIVE.value, nullable=False)
    # Avatar = storage KEY, never a URL (plan 06 D4 — presigned URLs expire).
    # The version cache-busts the public route; the old `avatar` URL column
    # is gone (it only ever held NULLs).
    avatar_key = Column(String, nullable=True)
    avatar_version = Column(Integer, nullable=False, default=0, server_default="0")
    # IANA timezone preference (plan sprint-2/05); NULL = render in browser tz.
    timezone = Column(String(64), nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_sign_in_at = Column(UTCDateTime(), nullable=True)
    email_verified_at = Column(UTCDateTime(), nullable=True)
    is_trashed = Column(Boolean, default=False, nullable=False)

    # Many-to-many roles. selectin avoids N+1 when listing users.
    roles = relationship("Role", secondary=user_roles, lazy="selectin")

    # joined: the per-request tenant-lifecycle check + platform gating read the
    # tenant (and its status, itself lazy="joined") on every authenticated
    # request — load them with the user row, never as a second query.
    tenant = relationship("Tenant", lazy="joined")

    @property
    def avatar(self) -> "str | None":
        """Wire-facing avatar URL — every serializer (login payload, /auth/me,
        users list) reads `.avatar` unchanged. Pure string concat from id +
        version: the PUBLIC route resolves the key per request (CDN/presigned/
        local), so nothing expiring is ever persisted or serialized here."""
        if not self.avatar_key:
            return None
        from app.config import settings

        return f"{settings.public_base_url}/public/avatars/{self.id}?v={self.avatar_version}"
