"""Ideation module models — all live in the ``app_ideation`` schema.

Slice 2 (AC-A-05..08): the **unified Product** doctrine. There is ONE Product
entity = the core ``public.products`` catalog; ideation does NOT own a products
table. What only a software product needs — a delivery origin + polymorphic
adapters — lives here as 1:N/1:1 EXTENSION tables keyed to ``public.products`` via
normal cross-schema FKs (referenced UNqualified so Postgres resolves them via
search_path and the SQLite test engine's ``schema_translate_map`` maps the module
schema away cleanly — see ``db.py``).

Every tenant-scoped table carries ``tenant_id``. Datetimes are tz-aware UTC.
"""
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func
from sqlalchemy.types import JSON

from app.models.catalog import Product
from app.models.status import Status
from app.models.utc_datetime import UTCDateTime
from modules.omnichannel.models import Contact

from .db import IdeationBase

# Normal cross-schema FK target = core ``public.products.id``. Reference the core
# COLUMN OBJECT (not a string) so it resolves across the two MetaData objects: a
# bare ``"products.id"`` string would resolve against this module's metadata
# (default schema ``app_ideation``) and fail. On Postgres this emits an
# unqualified ``REFERENCES products(id)`` (search_path → public); on the SQLite
# test engine the module schema is schema-translated onto an attached db and FK
# enforcement is off, so create_all maps cleanly (per db.py note).
_PRODUCT_FK = Product.__table__.c.id
# Core ``public.statuses.id`` — the Idea rides the core status engine (D-A3).
_STATUS_FK = Status.__table__.c.id
# Omnichannel ``app_omnichannel.contacts.id`` — the submitter is a shared-service
# contact copy (D-A4). Column-object FK resolves across the two MetaData objects.
_CONTACT_FK = Contact.__table__.c.id


def _uuid() -> str:
    return str(uuid.uuid4())


class ProductDelivery(IdeationBase):
    """Software-product delivery config (AC-A-06). 1:1 with a ``public.products``
    row (``product_id`` UNIQUE). ``product_domain_base`` is a validated absolute
    origin (e.g. ``https://fe-sorento.foundryx.my``) stored verbatim and used to
    mint product-domain idea links (``{product_domain_base}/ideas/{idea_id}``,
    AC-A-38). Only software products get a row; a product without one has no
    delivery origin yet."""

    __tablename__ = "product_delivery"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    # Normal cross-schema FK into core public.products (referenced UNqualified).
    product_id = Column(String, ForeignKey(_PRODUCT_FK), nullable=False, index=True)
    product_domain_base = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("product_id", name="uq_product_delivery_product"),
    )


class ProductAdapter(IdeationBase):
    """A polymorphic delivery adapter on a software Product (AC-A-07). ``kind`` is
    validated against the code-side adapter-kind registry (``adapters.py``) —
    ``embed_connection`` is Phase-A-wired; ``github``/``agent_runner``/``deploy``
    are registered-but-dormant (Phase C). ``config_json`` holds kind-specific
    settings (e.g. embed ``allowedOrigins``/``product_domain_base``);
    ``credentials_ref`` is an opaque pointer to a secret store (never a plaintext
    secret), nullable for kinds that need none."""

    __tablename__ = "product_adapters"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    product_id = Column(String, ForeignKey(_PRODUCT_FK), nullable=False, index=True)
    kind = Column(String, nullable=False)  # adapter-kind registry key
    config_json = Column(JSON, nullable=True)
    credentials_ref = Column(Text, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Idea(IdeationBase):
    """The rawest capture in the pipeline (Idea → BR → FR → delivery), against a
    core Product (AC-A-09). Rides the core **status engine** as a tenant-owned
    entity (``register_status_entity("idea", …)``, D-A3): ``status_id`` is a
    cross-schema FK into ``public.statuses`` and every move goes through
    ``status_machine.transition`` (draft→captured→triaged→linked→building→
    delivered→closed, + duplicate/rejected off-ramps; initial ``draft``).

    ``captured_json`` holds the form_engine answers for the ``ideation``
    IntakeDefinition; ``priority`` is the manual triage ordering. **No
    ``embedding`` column** — dedup is ``pg_trgm`` text-similarity (D-A6);
    shared-service runs no embedding model (D20)."""

    __tablename__ = "ideas"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    # Normal cross-schema FK into core public.products (one Product per Idea).
    product_id = Column(String, ForeignKey(_PRODUCT_FK), nullable=False, index=True)
    # Cross-schema FK into core public.statuses (the status engine's row).
    status_id = Column(String, ForeignKey(_STATUS_FK), nullable=False, index=True)
    intake_definition_key = Column(String, nullable=False, default="ideation")
    problem = Column(Text, nullable=False)
    # First-class segregated intake fields (mirror the captured_json answer keys —
    # problem / proposed_solution / impact / department). Nullable: they fill in as
    # the intake collects them, and operator-authored ideas may omit them. The read
    # serializer returns them camelCase; ``problem`` above is the required headline.
    proposed_solution = Column(Text, nullable=True)
    impact = Column(Text, nullable=True)
    department = Column(String, nullable=True)
    raw_text = Column(Text, nullable=False, default="")
    source = Column(String, nullable=False, default="manual")  # whatsapp|voice|manual
    # Cross-schema FK into omnichannel contacts (the synced submitter copy);
    # nullable until the submitter phone is matched/enriched (D-A4).
    submitter_contact_id = Column(
        String, ForeignKey(_CONTACT_FK), nullable=True, index=True
    )
    # Denormalized submitter display name for operator-authored ideas — an
    # in-app create has no contact copy (``submitter_contact_id`` stays NULL), so
    # the operator's name is stored directly here. The read serializer prefers
    # this when set, else derives the name from the linked contact (D-A4).
    submitter_name = Column(String, nullable=True)
    captured_json = Column(JSON, nullable=True)
    # Denormalized vote tallies, recomputed from ``idea_votes`` on every vote
    # (the source of truth is one row per voter). ``downvotes`` mirrors the FE
    # Idea shape; Phase A still centres on upvotes (D10).
    upvotes = Column(Integer, nullable=False, default=0)
    downvotes = Column(Integer, nullable=False, default=0)
    priority = Column(Integer, nullable=False, default=0)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# Same-schema FK target = the Idea above. Reference the column object (the table
# is schema-qualified ``app_ideation.ideas`` so a bare ``"ideas.id"`` string
# would not resolve by table-name key).
_IDEA_FK = Idea.__table__.c.id


class IdeaVote(IdeationBase):
    """One voter's vote on an Idea (AC-A-21 idempotency substrate). At most one
    row per ``(idea_id, voter_id)`` (UNIQUE) so a vote is idempotent and can be
    toggled/switched; ``dir`` is ``up`` | ``down``. ``voter_id`` holds the acting
    principal id — the operator ``users.id`` on the triage surface today; the
    conversational-intake submitter-upvote path (AC-A-21) reconciles onto the
    same table in its own slice. Idea vote tallies are recomputed from these
    rows, so this table is the source of truth for ``upvotes`` / ``downvotes``."""

    __tablename__ = "idea_votes"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    idea_id = Column(String, ForeignKey(_IDEA_FK), nullable=False, index=True)
    voter_id = Column(String, nullable=False, index=True)
    dir = Column(String, nullable=False)  # 'up' | 'down'
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("idea_id", "voter_id", name="uq_idea_vote_voter"),
    )


class EmbedConnection(IdeationBase):
    """Ideation iframe-embed SSO connection registry (PLAN-ideation-embed-sso §7,
    AC-E-5/12). One row per host application (e.g. sorento) authorised to embed a
    tenant's Ideas workspace. The ``connection_id`` is the shared, non-secret
    handle the host puts in its ``POST /embed/session`` body; ``signing_secret``
    is the HS256 secret BOTH sides hold — stored Fernet-encrypted at rest
    (``signing_secret_ciphertext``, via ``app.secrets.encrypt_secret``), never
    returned plaintext, never logged.

    ``allowed_origins`` is the parent-origin allow-list (the browser origins
    permitted to iframe the page). ``product_id`` optionally scopes the connection
    to a single core Product (nullable = all the tenant's ideas). ``is_active``
    disables a connection without deleting it (rotation / off-boarding).

    Verification (``services/embed.py``) resolves the connection by
    ``connection_id`` from the request body, decrypts the secret, and checks the
    assertion signature + ``aud="ideation-embed"`` + ``iss="sorento"`` + expiry
    against it — a rotated secret invalidates every outstanding assertion for that
    connection (blast radius = one connection)."""

    __tablename__ = "embed_connections"

    # The connection_id IS the primary key (unique handle the host sends).
    connection_id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    signing_secret_ciphertext = Column(Text, nullable=False)
    allowed_origins = Column(JSON, nullable=False, default=list)
    # Optional scope to one core public.products row; plain nullable id (no FK) so
    # a connection can be registered before any product exists.
    product_id = Column(String, nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
