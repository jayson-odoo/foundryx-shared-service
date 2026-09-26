"""Ideation API schemas - camelCase out to the frontend (mirrors
service_frontend/types/ideation.ts + services/ideation-service.ts).

The ``create_idea`` intake contract (§5.1, S1) is the exception: it is a
server-to-server contract with the sorento brain and uses **snake_case**
field names byte-for-byte (input schema below; the output is a plain dict
built in ``services/intake.py`` - it ALWAYS carries the full ten-key
envelope, null where not applicable (AC-1116), never an omitted key)."""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import Field

from app.schemas.base import ApiModel


class IdeaAttachmentOut(ApiModel):
    """An idea attachment (voice note, image, video, file). Empty until the
    create_idea / attachment slice lands - the detail section renders empty."""

    id: str
    kind: str
    name: str
    url: str = ""
    sizeBytes: Optional[int] = None
    durationSec: Optional[int] = None


class IdeaOut(ApiModel):
    """One Idea, matching the FE ``Idea`` shape (types/ideation.ts). ``status`` is
    the lifecycle KEY (e.g. ``captured``); ``productName``/``submitterName`` are
    human-readable (never a raw UUID - cursor rule). ``downvotes``/``myVote`` are
    surfaced for the FE contract but Phase A tracks upvotes only (D10)."""

    id: str
    productId: str
    productName: str
    status: str
    # A short (1-8 word) headline (S1, AC-1105/1106) - null for a pre-lane
    # idea or a draft that never sent one; the FE falls back to ``problem``.
    title: Optional[str] = None
    problem: str
    proposedSolution: Optional[str] = None
    impact: Optional[str] = None
    department: Optional[str] = None
    rawText: str
    source: str
    submitterName: str
    # The submitter's tier (e.g. ``dealer``, S1 AC-1115) - null when not set.
    submitterTier: Optional[str] = None
    upvotes: int
    downvotes: int = 0
    myVote: Optional[Literal["up", "down"]] = None
    priority: int
    attachments: List[IdeaAttachmentOut] = []
    createdAt: datetime
    # The formatted sequential idea number (S1/S5) - null until captured.
    # Never ``statusToken`` (that stays the public-status-page credential,
    # never surfaced on an authenticated read).
    ideaNumber: Optional[str] = None
    # A console/``--say`` test turn (issue #1179) - false for every real capture.
    # Excluded from list/board by default (``includeTest`` opts in).
    isTest: bool = False


class BoardColumnOut(ApiModel):
    """One triage-board column - a lifecycle status + the ideas parked in it.
    ``ideas`` are ordered by priority ascending (top = highest priority)."""

    key: str
    title: str
    ideas: List[IdeaOut] = []


class BoardOut(ApiModel):
    """The triage board (AC-A-33) - ideas grouped into the board lifecycle
    columns (captured → triaged → linked → building → delivered), in order.
    Archived / terminal ideas are off the board."""

    columns: List[BoardColumnOut] = []


class DeliveryConfigOut(ApiModel):
    """A software Product's delivery config (AC-A-06). ``productDomainBase`` is
    null until a Maintainer sets it."""

    productId: str
    productDomainBase: Optional[str] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


class DeliveryConfigIn(ApiModel):
    productDomainBase: str


class VoteIn(ApiModel):
    """Toggle the caller's vote on an idea (one per voter). Re-sending the same
    ``dir`` cancels it; the other ``dir`` switches it."""

    dir: Literal["up", "down"]


class ReorderIn(ApiModel):
    """Manual priority ranking - ``orderedIds`` top-to-bottom (index = priority,
    ascending = top)."""

    orderedIds: List[str]


class StatusIn(ApiModel):
    """Move an idea to a lifecycle status by KEY (e.g. ``triaged``, ``archived``,
    ``captured``). Server-authoritative - an illegal move is refused."""

    status: str


class IdeaCreateIn(ApiModel):
    """Operator-facing in-app idea create - **camelCase**, mirroring the FE
    ``IdeaCreateInput`` (services/ideation-service.ts). Distinct from the
    conversational ``CreateIdeaIn`` intake (snake_case, server-to-server): an
    operator typing an idea IS deliberate, so there is no draft/collect/confirm
    gate - it is created straight into ``captured``. ``productId`` is validated
    against the tenant catalog; ``source`` defaults to ``manual``."""

    productId: str
    problem: str
    proposedSolution: Optional[str] = None
    impact: Optional[str] = None
    department: Optional[str] = None
    rawText: str = ""
    source: str = "manual"


class IdeaUpdateIn(ApiModel):
    """Operator-facing in-app idea edit - partial update of the mutable fields.
    Status moves ride ``POST /ideation/ideas/{id}/status`` (server-authoritative),
    NOT this route, so ``status`` is intentionally absent."""

    productId: Optional[str] = None
    problem: Optional[str] = None
    proposedSolution: Optional[str] = None
    impact: Optional[str] = None
    department: Optional[str] = None
    rawText: Optional[str] = None


class CreateIdeaAttachmentIn(ApiModel):
    """One resolved media attachment on a ``create_idea`` turn (§5.1 ``attachments[]``,
    DC-9) - **snake_case, server-to-server**. Sorento has already snapshotted the
    Respond CDN bytes to durable storage (R2/S3) and, for images, run a vision
    caption; shared-service persists this pointer as-is and fetches nothing.

    ``source_msg_id`` (the originating Respond.io message id) is the **idempotency
    key** - the same media re-sent across turns upserts one row. ``type`` ∈
    ``image|video|file|audio`` (stored as the model's ``kind``). ``caption`` is the
    vision description / transcript note for the detail UI (the idea's text already
    carries it - sorento folds it into ``message_text``)."""

    source_msg_id: str
    url: str
    type: Literal["image", "video", "file", "audio"]
    filename: Optional[str] = None
    caption: Optional[str] = None


class BusinessRequirementOut(ApiModel):
    """One Business Requirement (list row / detail base), camelCase to the FE.
    ``status`` is the lifecycle KEY; ``statusLabel``/``statusColor`` are the
    server-rendered display (never branch on the label). ``templateVersion`` is
    the STAMPED version this BR renders against (AC-BI-16)."""

    id: str
    productId: str
    productName: str
    status: str
    statusLabel: str
    statusColor: str
    templateKey: str
    templateVersion: int
    title: str
    ideaCount: int = 0
    isTest: bool = False
    createdAt: datetime
    updatedAt: datetime


class BusinessRequirementDetailOut(BusinessRequirementOut):
    """The BR detail - adds ``answers`` (the form_engine answer map) and
    ``templateDoc`` (the STAMPED template version's block document, for the
    form-engine renderer on the Details tab)."""

    answers: Dict[str, Any] = {}
    templateDoc: Dict[str, Any] = {}


class BrTemplateVersionOut(ApiModel):
    """One BR-template version (Versions tab). ``isStamped`` marks the version
    THIS BR renders against; ``isActive`` marks the template's current label."""

    version: int
    isStamped: bool
    isActive: bool
    createdAt: datetime


class BusinessRequirementCreateIn(ApiModel):
    """Create a draft BR against a product. ``answers`` are validated against the
    stamped template version; ``ideaIds`` optionally links ideas (same product)."""

    productId: str
    title: str = ""
    answers: Optional[Dict[str, Any]] = None
    ideaIds: Optional[List[str]] = None


class BusinessRequirementUpdateIn(ApiModel):
    """Partial edit of a BR's ``title`` / ``answers`` (validated against the
    STAMPED version). Status moves ride ``POST /{id}/status``, not this route."""

    title: Optional[str] = None
    answers: Optional[Dict[str, Any]] = None


class BrLinkIdeasIn(ApiModel):
    """Link ideas to a BR (tenant-scoped + same-product, AC-BI-17)."""

    ideaIds: List[str]


class BrTemplateStatusOut(ApiModel):
    """Issue #90 W2 - whether a BR create would succeed right now (an active
    template resolves to a version). Backs the "New business requirement"
    dialog's guard so it can explain the failure instead of only refusing."""

    active: bool


class BrStatusIn(ApiModel):
    """Move a BR to a lifecycle status by KEY - server-authoritative."""

    status: str


# ── clustering (Phase B-i slice 4, AC-BI-30/31) ──────────────────────────────


class ClusterSuggestionOut(ApiModel):
    """One suggested idea cluster (AC-BI-30). ``ideas`` carries the resolved rows
    so the board can render + edit the selection before promotion. A cluster is
    ALWAYS a suggestion - nothing auto-promotes (AC-BI-31)."""

    label: str
    productId: str
    ideaIds: List[str] = []
    ideas: List[IdeaOut] = []


class ClusterSuggestionsOut(ApiModel):
    """Cluster suggestions for a product / the whole tenant. ``degraded`` = the
    LLM grouping was unavailable so trigram candidates are returned ungrouped
    (AC-BI-30) - clustering degrades, never blocks the board."""

    clusters: List[ClusterSuggestionOut] = []
    degraded: bool = False


# ── Grill (Phase B-i slice 3, AC-BI-20..29) ──────────────────────────────────


class GrillFieldOut(ApiModel):
    """One target field the grill drives toward (key + display label)."""

    key: str
    label: str


class GrillMessageOut(ApiModel):
    """One transcript turn (AC-BI-21). ``coveredFields`` is the assistant turn's
    coverage map (empty for user turns)."""

    id: str
    role: str
    content: str
    coveredFields: List[str] = []
    createdAt: datetime


class GrillStateOut(ApiModel):
    """The Grill tab's snapshot: readiness + fields + transcript + coverage.
    ``ready``/``warning`` carry the prerequisite state (AC-BI-11).
    ``capturedSummary`` is the latest turn's per-field understood values
    (AC-BI-24c) - the running summary the panel renders."""

    ready: bool
    warning: Optional[str] = None
    agentName: str
    fields: List[GrillFieldOut] = []
    messages: List[GrillMessageOut] = []
    coveredFields: List[str] = []
    capturedSummary: Dict[str, str] = {}


class GrillTurnIn(ApiModel):
    """One human turn."""

    message: str


class GrillTurnOut(ApiModel):
    """The turn response (AC-BI-22/24b/24c): prose reply + the coverage map + the
    running captured summary + the generate signal, all from ONE structured call.
    ``generateSignal`` TRUE = the user asked to finalize; the APP fires Generate
    (the model has no side-effect tool, D22-A)."""

    replyText: str
    coveredFields: List[str] = []
    capturedSummary: Dict[str, str] = {}
    generateSignal: bool = False


class GrillGenerateOut(ApiModel):
    """The Generate result. ``status='ok'`` → ``br`` carries the updated detail
    (Details tab refreshes); ``status='needs_review'`` → ``fieldErrors`` after a
    failed extraction + one retry (AC-BI-25), the BR is left unchanged."""

    status: Literal["ok", "needs_review"]
    br: Optional[BusinessRequirementDetailOut] = None
    answers: Dict[str, Any] = {}
    fieldErrors: Dict[str, str] = {}


class CreateIdeaIn(ApiModel):
    """``create_idea`` intake input (§5.1, AC-A-17) - **snake_case, byte-for-byte**.

    ``product_id`` is validated against the workspace's catalog; ``fields`` are the
    sorento-brain-extracted answer updates; ``remove`` clears answer keys;
    ``confirm`` is the explicit user confirmation (D-CONFIRM - shared-service never
    infers it). ``draft_id`` is absent on turn 1, present on continuation."""

    product_id: str
    submitter_contact_id: Optional[str] = None
    # Human display name of the sender, resolved host-side (sorento respond_contacts
    # → n8n Respond.io-profile fallback). Stored verbatim on the Idea so the UI
    # shows a name, not "Unknown". Shared-service NEVER queries respond_contacts
    # (D20 - it just persists the string). WS-A / AC-CAP-1..3.
    submitter_name: Optional[str] = None
    message_text: str = ""
    # The CUMULATIVE conversation transcript that produced the idea (host-owned;
    # sorento accumulates across turns). When present it is stored as the Idea's
    # ``raw_text`` (the whole convo, not just the last "okay i confirm" turn);
    # ``message_text`` stays the current turn for extraction/dedup. WS-B / AC-CAP-5..7.
    raw_transcript: Optional[str] = None
    # Unified media array (DC-9) - voice/image/video/file, each already durably
    # stored + captioned host-side. Retires the singular ``audio_attachment_ref``.
    attachments: Optional[List[CreateIdeaAttachmentIn]] = None
    draft_id: Optional[str] = None
    # An abandoned draft to reject on an ``is_new_idea`` restart (DC-10): the host
    # detected the user starting a genuinely new idea while an old draft was open,
    # so it opens a fresh draft (no ``draft_id``) and names the stale one here.
    discard_draft_id: Optional[str] = None
    fields: Optional[Dict[str, Any]] = None
    remove: Optional[List[str]] = None
    confirm: bool = False
    # A console/``--say`` test turn (owner ruling 24 Sep 2026, issue #1179): the
    # ideate lane calls this REAL endpoint on a test turn instead of a fixed
    # placeholder, and sets this so the row stays off the board/list and out of
    # dedup/promotion by default while the reply text can still be checked.
    # Stamped once on the draft's creation turn; later turns keep whatever the
    # draft was created with regardless of what this carries.
    is_test: bool = False
    # ── S1 intake-contract additions (all additive, optional) ────────────────
    # A short (1-8 word) headline (AC-1105) - 1-8 words checked server-side
    # (``title_too_long`` 422 otherwise); blank/whitespace is treated as
    # absent. Latest non-blank value across turns wins.
    title: Optional[str] = None
    # Optional schema keys to skip (AC-1103) - only ``proposed_solution`` /
    # ``impact`` are ever honored (``problem`` and unknown keys are ignored);
    # answering a key later un-skips it (answer wins).
    skip: Optional[List[str]] = None
    # Explicit abandon (AC-1113) - closes the draft (``rejected``), status
    # ``cancelled``, idempotent on a later call with the same draft_id.
    cancel: Optional[bool] = None
    # The submitter's choice on an open ``duplicate_candidate`` (AC-1109/1110);
    # ignored when there is no pending candidate on this draft.
    duplicate_choice: Optional[Literal["vote", "separate"]] = None
    # The submitter's tier (e.g. ``dealer``, AC-1115) - stored verbatim,
    # stripped; latest non-blank value across turns wins.
    submitter_tier: Optional[str] = None


class PublicIdeaTimelineStepOut(ApiModel):
    """One step of the public status timeline (issue #90, AC-90-1xx) -
    ``state`` is derived server-side from the tenant's status set (trait
    flags, never ``category``); the frontend only renders it."""

    label: str
    color: str
    state: Literal["done", "current", "upcoming"]


class PublicIdeaStatusOut(ApiModel):
    """The public idea-status page contract - GET /public/ideas/{token}, no
    auth. Issue #90 widens this from the original 3-key contract
    (title/status/ideaNumber) to a full page; the EXACT key set is pinned by
    ``test_public_status_exact_key_set_and_no_pii`` (AC-90-104) so a future
    field cannot leak silently. ``status`` stays the status LABEL (e.g.
    ``New``), never the lifecycle key. No id, no tenant id, no last name, no
    phone/email, no raw transcript - see the router/service docstrings for
    the full forbidden-field rationale."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    title: Optional[str] = None
    status: str
    ideaNumber: Optional[str] = Field(default=None, validation_alias="idea_number")
    statusColor: str
    productName: Optional[str] = None
    problem: Optional[str] = None
    proposedSolution: Optional[str] = None
    impact: Optional[str] = None
    department: Optional[str] = None
    submitterFirstName: Optional[str] = None
    submittedAt: Optional[datetime] = None
    upvotes: int = 0
    nextStep: str
    timeline: List[PublicIdeaTimelineStepOut] = Field(default_factory=list)
