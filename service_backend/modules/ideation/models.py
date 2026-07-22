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
    Index,
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


class IdeaAttachment(IdeationBase):
    """A media attachment on an Idea — voice note / image / video / file captured
    over WhatsApp (§5.1 ``attachments[]``, DC-9). Written by the ``create_idea``
    intake when the sorento brain has resolved + durably stored the media (sorento
    snapshots the Respond CDN bytes to R2/S3 and passes a durable ``url``); this
    table only persists the resolved pointer + metadata — shared-service fetches
    nothing.

    ``source_msg_id`` is the originating Respond.io message id; it is the
    **idempotency key** — the same media re-sent across turns (or a retried turn)
    upserts the one row, never duplicates (``UNIQUE(idea_id, source_msg_id)``).
    ``kind`` ∈ ``image|video|file|audio``. ``caption`` is the host-side vision
    description (image) or STT transcript note (audio), stored for the detail UI;
    the idea's textual content already carries it (sorento folds the caption into
    ``message_text``), so this column is display-only."""

    __tablename__ = "idea_attachments"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    idea_id = Column(String, ForeignKey(_IDEA_FK), nullable=False, index=True)
    # Respond.io message id — idempotency key (see UniqueConstraint below).
    source_msg_id = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # image | video | file | audio
    url = Column(Text, nullable=False)  # durable sorento-stored URL (R2/S3)
    filename = Column(String, nullable=True)
    caption = Column(Text, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "idea_id", "source_msg_id", name="uq_idea_attachment_source_msg"
        ),
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


# ── Business Requirement entity (Phase B-i slice 2, AC-BI-15..19) ─────────────


class IdeationArtifactTemplate(IdeationBase):
    """A versioned artifact template keyed by ``template_key`` (Bi-D1/Bi-D2) —
    modelled EXACTLY on core's ``ai_skills`` shape: a movable ``active_version_id``
    label over immutable ``ideation_artifact_template_versions`` rows. A template
    body is a ``form_engine`` ``FormDocument`` (block-doc, not a wide column set).

    ``tenant_id IS NULL`` = the platform tier (the only tier S2 seeds — no
    per-tenant fork yet; tenant customization is deferred). No FK on
    ``active_version_id`` — the version rows FK back to the template, and a mutual
    FK pair deadlocks insert ordering (the ai_skills lesson)."""

    __tablename__ = "ideation_artifact_templates"

    id = Column(String, primary_key=True, default=_uuid)
    # Plain nullable id (no FK): NULL = platform tier. Cross-schema to core is
    # BL-030 (plain indexed column) anyway, and the platform tier has no tenant.
    tenant_id = Column(String, nullable=True, index=True)
    template_key = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    # The movable ``active`` label (no FK — see class docstring).
    active_version_id = Column(String, nullable=True, index=True)
    is_system = Column(Boolean, nullable=False, default=False)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        # Two-tier uniqueness needs PARTIAL indexes per tier (the ai_skills /
        # BL-065 lesson): a plain unique over a nullable column doesn't constrain
        # the platform (NULL) tier on Postgres.
        Index(
            "uq_ideation_artifact_tmpl_tenant_key",
            "tenant_id",
            "template_key",
            unique=True,
            postgresql_where=Column("tenant_id").isnot(None),
            sqlite_where=Column("tenant_id").isnot(None),
        ),
        Index(
            "uq_ideation_artifact_tmpl_platform_key",
            "template_key",
            unique=True,
            postgresql_where=Column("tenant_id").is_(None),
            sqlite_where=Column("tenant_id").is_(None),
        ),
    )


# Same-schema FK target = the artifact-template above.
_TEMPLATE_FK = IdeationArtifactTemplate.__table__.c.id


class IdeationArtifactTemplateVersion(IdeationBase):
    """IMMUTABLE template body (a ``form_engine`` ``FormDocument`` in ``doc_json``).
    Never updated in place — an edit inserts the next version and the template's
    ``active_version_id`` label moves (Bi-D2). A BR STAMPS ``(template_key,
    version)`` at create so historical BRs render against their own version even
    after the template is edited (AC-BI-16)."""

    __tablename__ = "ideation_artifact_template_versions"

    id = Column(String, primary_key=True, default=_uuid)
    # Intra-schema FK to the owning template (same schema — real FK kept).
    template_id = Column(String, ForeignKey(_TEMPLATE_FK), nullable=False, index=True)
    # Denormalised so version reads stay tenant-scoped without a join (NULL =
    # platform tier, mirrors the parent).
    tenant_id = Column(String, nullable=True, index=True)
    version = Column(Integer, nullable=False)
    # The form_engine block document (validate_form_doc-valid).
    doc_json = Column(JSON(none_as_null=True), nullable=False)
    created_by = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index(
            "uq_ideation_artifact_tmpl_ver",
            "template_id",
            "version",
            unique=True,
        ),
    )


class BusinessRequirement(IdeationBase):
    """A Business Requirement (Idea → BR → FR → delivery, AC-BI-15). Rides the
    core status engine as an UNSCOPED, tenant-owned entity
    (``register_status_entity("ideation_business_requirement", …)``, Bi-D3):
    lifecycle ``draft → grilling → ready → in-FR → delivered → archived``,
    initial ``draft``.

    ``answers_json`` holds the ``form_engine`` answers, validated at write against
    the STAMPED template version (``template_key`` + ``template_version``), never
    the current active one (AC-BI-16). Refs to core (``tenant_id`` /
    ``product_id`` / ``status_id`` / ``created_by`` / ``updated_by``) are PLAIN
    INDEXED columns — NO DB ForeignKey (BL-030)."""

    __tablename__ = "business_requirements"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    # Plain indexed cross-schema refs to core (BL-030) — no DB FK.
    product_id = Column(String, nullable=False, index=True)
    status_id = Column(String, nullable=False, index=True)
    # The stamped template identity (AC-BI-16). answers_json is validated against
    # THIS version, resolved by (template_key, template_version).
    template_key = Column(String, nullable=False)
    template_version = Column(Integer, nullable=False)
    title = Column(String, nullable=False, default="")
    answers_json = Column(JSON(none_as_null=True), nullable=True)
    created_by = Column(String, nullable=True, index=True)
    updated_by = Column(String, nullable=True, index=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# Same-schema FK target = the BR above.
_BR_FK = BusinessRequirement.__table__.c.id


class IdeaBusinessRequirement(IdeationBase):
    """Idea ↔ BR many-many join (D4, AC-BI-17). An Idea may feed several BRs and a
    BR may absorb many Ideas. ``business_requirement_id`` keeps its intra-schema FK
    (``business_requirements`` is created in the same migration — no contention),
    but ``idea_id`` is a **plain indexed column, NOT a DB FK**: ``ideas`` is a hot,
    pre-existing table, and adding a FK to it in the 0008 migration takes a
    ``SHARE ROW EXCLUSIVE`` lock that HANGS a blue/green deploy behind any live
    connection touching ``ideas`` (observed: backend_green never healthy). The
    BL-030 rule — references to hot/pre-existing tables are plain indexed columns —
    applies exactly here. ``tenant_id`` is derived from the pair at insert (never a
    static default) and the link is validated tenant-scoped + same-product on
    write, so integrity is enforced in the service layer regardless."""

    __tablename__ = "idea_business_requirements"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    idea_id = Column(String, nullable=False, index=True)
    business_requirement_id = Column(
        String, ForeignKey(_BR_FK), nullable=False, index=True
    )
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "idea_id",
            "business_requirement_id",
            name="uq_idea_business_requirement",
        ),
    )
