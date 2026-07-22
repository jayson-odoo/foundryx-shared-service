/**
 * Grill types (Phase B-i slice 3, AC-BI-20..29) — the FE side of the ideation
 * grill backend contract (modules/ideation/routers/grill.py). The grill turns a
 * draft BR into a well-formed requirement through a bounded clarifying
 * conversation; the human ends it with Generate.
 */
import type { BusinessRequirementDetail } from '@/types/business-requirement';

/** A transcript role. `user` = the human, `assistant` = the grill. */
export type GrillRole = 'user' | 'assistant';

/** One target field the grill drives toward (answer key + display label). */
export interface GrillField {
  key: string;
  label: string;
}

/** One transcript turn. `coveredFields` is the assistant turn's coverage map
 * (empty for user turns). */
export interface GrillMessage {
  id: string;
  role: GrillRole;
  content: string;
  coveredFields: string[];
  createdAt: string;
}

/** The Grill tab snapshot: readiness + fields + transcript + coverage.
 * `ready`/`warning` carry the prerequisite state (AC-BI-11). `capturedSummary`
 * is the latest turn's per-field understood values (AC-BI-24c). */
export interface GrillState {
  ready: boolean;
  warning: string | null;
  agentName: string;
  fields: GrillField[];
  messages: GrillMessage[];
  coveredFields: string[];
  capturedSummary: Record<string, string>;
}

/** The turn response (AC-BI-22/24b/24c): prose reply + the coverage map + the
 * running captured summary + the generate signal, all from ONE structured call.
 * `generateSignal` true = the user asked to finalize; the APP fires Generate
 * (the model has no side-effect tool, D22-A). */
export interface GrillTurn {
  replyText: string;
  coveredFields: string[];
  capturedSummary: Record<string, string>;
  generateSignal: boolean;
}

/** The Generate result. `ok` → `br` carries the refreshed detail (Details tab
 * refreshes); `needs_review` → `fieldErrors` after a failed extraction + one
 * retry (AC-BI-25), the BR is left unchanged. */
export interface GrillGenerate {
  status: 'ok' | 'needs_review';
  br: BusinessRequirementDetail | null;
  answers: Record<string, unknown>;
  fieldErrors: Record<string, string>;
}
