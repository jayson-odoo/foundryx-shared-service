/**
 * Business Requirement types (Phase B-i slice 2, AC-BI-15..19) - the FE side of
 * the ideation BR backend contract (modules/ideation/schemas.py). A BR is the
 * second stage of the pipeline (Idea → BR → FR → delivery); its `answers` render
 * through the form-engine renderer against its STAMPED template doc.
 */
import type { FormAnswers, FormDocument } from '@/types/forms';

/** BR lifecycle keys (mirror the seeded status graph, AC-BI-15). */
export type BusinessRequirementStatus =
  | 'draft'
  | 'grilling'
  | 'ready'
  | 'sent_to_build'
  | 'in_fr'
  | 'delivered'
  | 'archived';

/** One BR row (list) / detail base. `status` is the lifecycle KEY; the label +
 * color are server-rendered (never branch on the label). */
export interface BusinessRequirement {
  id: string;
  productId: string;
  productName: string;
  status: string;
  statusLabel: string;
  statusColor: string;
  templateKey: string;
  templateVersion: number;
  title: string;
  ideaCount: number;
  createdAt: string;
  updatedAt: string;
  /** A test idea (owner ruling 26 Sep ~12:50Z, issue #90 W3) may promote to a
   * TEST Business Requirement - excluded from the real list/counts, labelled
   * Test on its page. Optional so older fixtures/mocks default falsy. */
  isTest?: boolean;
}

/** One Trace entry of a BR's build (`sent` by a human, `crew` progress via the
 * write-back key, `system`). Append-only; `seq` orders the timeline. */
export interface BuildEvent {
  id: string;
  seq: number;
  kind: 'sent' | 'crew' | 'system';
  stage: string;
  message: string;
  prUrl: string | null;
  handtestUrl: string | null;
  status: 'in_progress' | 'merged' | 'released' | 'failed' | 'cancelled' | null;
  statusMoved: boolean;
  actorName: string | null;
  createdAt: string;
}

/** The BR's Send-to-build state (server-computed): readiness (`canSend` +
 * `blockers`) and, once sent, the issue + the Trace. */
export interface BuildInfo {
  canSend: boolean;
  /** A send edge leaves the BR's current status (false for in FR, delivered,
   * archived: the header keeps the plain Edit primary). */
  sendEdgeAvailable: boolean;
  blockers: string[];
  repo: string | null;
  issueUrl: string | null;
  issueNumber: number | null;
  state: 'none' | 'creating' | 'sent' | 'delivered' | 'failed';
  sentAt: string | null;
  sentBy: { id: string; name: string } | null;
  stage: string | null;
  prUrl: string | null;
  handtestUrl: string | null;
  events: BuildEvent[];
}

/** One issued build write-back key (never carries the plaintext). */
export interface BuildKey {
  id: string;
  name: string;
  keyPrefix: string;
  createdAt: string;
  lastUsedAt: string | null;
}

/** Mint response: the plaintext is shown ONCE. */
export interface BuildKeyMinted extends BuildKey {
  plaintext: string;
}

/** BR detail - adds the answer map + the STAMPED template block document. */
export interface BusinessRequirementDetail extends BusinessRequirement {
  answers: FormAnswers;
  templateDoc: FormDocument;
  build: BuildInfo;
}

/** One BR-template version (Versions tab). `isStamped` marks the version this BR
 * renders against forever (AC-BI-16). */
export interface BrTemplateVersion {
  version: number;
  isStamped: boolean;
  isActive: boolean;
  createdAt: string;
}

/** Create a draft BR against a product; `answers` validate against the stamped
 * version, `ideaIds` optionally links same-product ideas. */
export interface BusinessRequirementCreateInput {
  productId: string;
  title?: string;
  answers?: FormAnswers;
  ideaIds?: string[];
}

/** Partial edit - title and/or answers (validated against the stamped version). */
export interface BusinessRequirementUpdateInput {
  title?: string;
  answers?: FormAnswers;
}
