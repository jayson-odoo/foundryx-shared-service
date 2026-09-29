/**
 * Ideation module types (plan: documentation/plans/ideation/, Phase A - Capture).
 * The Idea is the rawest capture in the pipeline (Idea → BR → FR → delivery).
 * Kept thin per the plan; BR/FR land in Phase B. These shapes ARE the FE side
 * of the backend contract (§5 of the program master) - Phase-1 uses the mock
 * service; Phase-2 binds the real api-client impl.
 */

/** A software/goods product an idea targets (kind drives delivery adapters). */
export interface Product {
  id: string;
  name: string;
  kind: 'software' | 'goods';
  /** Base URL used to mint product-domain idea links (software products). */
  productDomainBase?: string | null;
}

/** How the idea entered the repository (the "channel"). */
export type IdeaSource = 'whatsapp' | 'voice' | 'manual';

/** An attachment on an idea - voice note, image, video, or generic file. */
export type IdeaAttachmentKind = 'audio' | 'image' | 'video' | 'file';

export interface IdeaAttachment {
  id: string;
  kind: IdeaAttachmentKind;
  /** User-facing filename (never a UUID/storage key). */
  name: string;
  /** Preview/download URL (mock: a placeholder or data URI in Phase 1). */
  url: string;
  sizeBytes?: number;
  /** Seconds - audio/video only. */
  durationSec?: number;
  /** Relative serve path of an UPLOADED file (fetched as a blob through the
   * api-client); null/absent for a URL-backed WhatsApp capture. */
  contentPath?: string | null;
}

/** One transition the caller may fire from an idea's current status (issue
 * #94, ideation round 2, AC-94-51) - `status_machine.fireable_edge_ids`,
 * never a hardcoded key. */
export interface IdeaTransition {
  id: string;
  label: string;
  toStatusId: string;
  toStatusLabel: string;
}

/** A minimal reference to another idea (the merge survivor or the pre-merge
 * kept idea) - never the full record, just enough to link + label (AC-94-26). */
export interface IdeaRef {
  id: string;
  ideaNumber: string | null;
  title: string | null;
}

export interface Idea {
  id: string;
  productId: string;
  /** Denormalized for display - the FE never renders the UUID (cursor rule). */
  productName: string;
  /** The lifecycle status KEY - display comes from `statusLabel`/`statusColor`
   * (issue #94, ideation round 2: the statuses engine, never a hardcoded
   * union - AC-94-55). */
  status: string;
  /** The tenant's resolved status row id for `status` (AC-94-49). */
  statusId?: string;
  /** Engine-resolved display label for `status` (e.g. "Discussed"). */
  statusLabel?: string;
  /** Engine-resolved display color (name or hex - `colorToHex`/`colorToTone`). */
  statusColor?: string;
  /** Trait flag - true when `status` is one of the tier's archived statuses
   * (AC-94-54/60) - never inferred from the key. */
  statusIsArchived?: boolean;
  /** The edges fireable from this idea's current status, for THIS caller
   * (role/condition filtered, `always=True`, AC-94-51). */
  transitions?: IdeaTransition[];
  /** Among `transitions`, the one that advances to the next stage by sort
   * order (AC-94-52) - `null` at a terminal stage, `undefined` before the
   * backend serializes it. */
  advanceTransitionId?: string | null;
  /** 1-based position among the caller-scope's active survivors
   * (AC-94-41..45) - `null` for archived/merged ideas, `undefined` before the
   * backend serializes it. NEVER render the raw `priority` instead. */
  rank?: number | null;
  /** Set when this idea was merged into another (AC-94-01..09) - `null`/
   * `undefined` for a plain idea or a survivor. */
  mergedIntoId?: string | null;
  /** The survivor this idea was merged into, resolved (AC-94-03). */
  mergedInto?: IdeaRef | null;
  /** Count of ideas merged INTO this one (0 for a plain idea or a child). */
  mergedCount?: number;
  /** A short (1-8 word) headline (S1) - the visible label when set; falls
   * back to `problem` when null (a pre-lane idea, or a draft that never sent
   * one). Optional so existing fixtures/callers need no change. */
  title?: string | null;
  /** One-line problem/observation (the headline on cards). */
  problem: string;
  /** Proposed solution - a segregated intake field (nullable until captured). */
  proposedSolution?: string | null;
  /** Impact of solving it - a segregated intake field (nullable until captured). */
  impact?: string | null;
  /** Owning department - a segregated intake field (nullable until captured). */
  department?: string | null;
  /** The rawest input as captured (verbatim WhatsApp/voice text or typed). */
  rawText: string;
  /** The channel the idea arrived on. */
  source: IdeaSource;
  /** Submitter display name (resolved from the synced contact - never a UUID). */
  submitterName: string;
  /** The submitter's tier (e.g. `dealer`, S1) - null/absent when not set. */
  submitterTier?: string | null;
  upvotes: number;
  downvotes: number;
  /** The current user's vote on this idea (one per user, toggleable). */
  myVote: 'up' | 'down' | null;
  /** Manual priority rank (ascending = higher priority); drag-to-reorder sets it. */
  priority: number;
  attachments: IdeaAttachment[];
  createdAt: string; // ISO
  /** The formatted sequential idea number (S1/S5, e.g. `IDEA-0182`) - null
   * until captured. */
  ideaNumber?: string | null;
  /** A console/`--say` test turn (issue #1179) - false for every real capture.
   * Excluded from the list/board by default; `includeTest` opts in. */
  isTest: boolean;
}

/** One suggested idea cluster (AC-BI-30/31). A cluster is ALWAYS a suggestion -
 * fully editable before promotion; nothing auto-promotes. */
export interface IdeaCluster {
  label: string;
  productId: string;
  ideaIds: string[];
  ideas: Idea[];
}

/** Cluster suggestions envelope. `degraded` = the LLM grouping was unavailable
 * so trigram candidates are returned ungrouped (clustering degrades, never
 * blocks the board). */
export interface IdeaClusterSuggestions {
  clusters: IdeaCluster[];
  degraded: boolean;
}

export const IDEA_SOURCE_LABEL: Record<IdeaSource, string> = {
  whatsapp: 'WhatsApp',
  voice: 'Voice note',
  manual: 'Manual',
};

/** One triage-board column - a tenant status (trait-filtered, never a
 * hardcoded key) + the ideas parked in it, ordered by rank (issue #94,
 * ideation round 2, AC-94-54/58). */
export interface BoardColumn {
  /** The tenant's resolved status row id - the drop target for a drag. */
  statusId: string;
  /** The lifecycle status key (stable across a rename). */
  key: string;
  /** Engine-resolved display label (e.g. "Discussed"). */
  title: string;
  /** Engine-resolved display color. */
  color: string;
  ideas: Idea[];
}

export interface Board {
  columns: BoardColumn[];
}

/** One step of the public idea-status timeline (issue #90 W1, AC-90-102/103) -
 * the tenant's status set in order, `state` marking where the idea sits. */
export interface PublicIdeaTimelineStep {
  label: string;
  color: string;
  state: 'done' | 'current' | 'upcoming';
}

/** The survivor named on a merged child's public page (issue #94, AC-94-13/14)
 * - `id`-free (the public page never surfaces a raw id, and never the
 * survivor's submitter - AC-94-14). */
export interface PublicMergedInto {
  ideaNumber: string | null;
  title: string | null;
}

/** The public idea-status page contract (GET /public/ideas/{token}), grown from
 * the S5 3-key contract into the full page by issue #90 W1 - no auth, the
 * token itself is the capability. `status` is the display LABEL (e.g. `New`),
 * never the lifecycle key. `statusColor` is non-nullable (matches
 * `PublicIdeaStatusOut.statusColor: str` in `modules/ideation/schemas.py` -
 * every status row carries a color). Every OTHER field beyond
 * `title`/`status`/`ideaNumber`/`statusColor` is nullable so an unset idea
 * field never breaks the page (foolproof render, never omission - AC-90-104
 * pins the exact key set / no-PII contract). `mergedInto` (issue #94,
 * AC-94-13/14) is set only when this idea is a merged child - its content
 * fields above stay its OWN, while `status`/`statusColor`/`timeline`/
 * `nextStep`/`upvotes` are then the SURVIVOR's (plan section 3.4). Optional
 * (not just nullable) so an older fixture/test double needs no change. */
export interface PublicIdeaStatus {
  title: string | null;
  status: string;
  ideaNumber: string | null;
  statusColor: string;
  productName: string | null;
  problem: string | null;
  proposedSolution: string | null;
  impact: string | null;
  department: string | null;
  submitterFirstName: string | null;
  submittedAt: string | null;
  upvotes: number;
  nextStep: string;
  timeline: PublicIdeaTimelineStep[];
  mergedInto?: PublicMergedInto | null;
}
