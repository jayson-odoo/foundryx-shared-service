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

/**
 * Idea lifecycle (program master §3). `captured` = intake complete; the triage
 * board moves it through `triaged → linked → building → delivered`. `duplicate`
 * / `rejected` are terminal off-ramps; `draft` is the mid-capture state (only
 * seen while the WhatsApp collect-loop is still gathering fields).
 */
export type IdeaStatus =
  | 'draft'
  | 'captured'
  | 'triaged'
  | 'linked'
  | 'building'
  | 'delivered'
  | 'closed'
  | 'duplicate'
  | 'rejected'
  | 'archived';

/**
 * Lifecycle transitions (prototype stand-in for the shared **status_engine**).
 * Phase 2 replaces this map with the status_engine's per-tenant transition graph
 * (which can offer multiple valid next-states); the UI reads allowed transitions
 * from the engine instead of this constant.
 */
export const IDEA_NEXT_STATUS: Partial<Record<IdeaStatus, IdeaStatus>> = {
  captured: 'triaged',
  triaged: 'linked',
  linked: 'building',
  building: 'delivered',
  delivered: 'closed',
};

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
}

export interface Idea {
  id: string;
  productId: string;
  /** Denormalized for display - the FE never renders the UUID (cursor rule). */
  productName: string;
  status: IdeaStatus;
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
  upvotes: number;
  downvotes: number;
  /** The current user's vote on this idea (one per user, toggleable). */
  myVote: 'up' | 'down' | null;
  /** Manual priority rank (ascending = higher priority); drag-to-reorder sets it. */
  priority: number;
  attachments: IdeaAttachment[];
  createdAt: string; // ISO
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

/** Board columns = the triage-relevant statuses, left→right flow. */
export const IDEA_BOARD_COLUMNS: { key: IdeaStatus; title: string }[] = [
  { key: 'captured', title: 'New' },
  { key: 'triaged', title: 'Triaged' },
  { key: 'linked', title: 'Linked to BR' },
  { key: 'building', title: 'Building' },
  { key: 'delivered', title: 'Delivered' },
];

export const IDEA_SOURCE_LABEL: Record<IdeaSource, string> = {
  whatsapp: 'WhatsApp',
  voice: 'Voice note',
  manual: 'Manual',
};

export const IDEA_STATUS_LABEL: Record<IdeaStatus, string> = {
  draft: 'Draft',
  captured: 'New',
  triaged: 'Triaged',
  linked: 'Linked to BR',
  building: 'Building',
  delivered: 'Delivered',
  closed: 'Closed',
  duplicate: 'Duplicate',
  rejected: 'Rejected',
  archived: 'Archived',
};
