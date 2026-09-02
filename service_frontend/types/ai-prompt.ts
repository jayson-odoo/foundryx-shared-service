/**
 * AI prompt registry wire types (Meetings S4 plan §3.3 / §3.4).
 *
 * Two-table mechanism ported from sorento's `ai_prompt_versions` +
 * `ai_prompt_labels` (R4): versions are immutable and append-only, a label
 * ("production" | "staging") is a movable pointer at one version. The v1
 * editor UI surfaces `production` only - `staging` rides along on the wire
 * shape (it costs nothing) but has no button yet; trigger to add one: a
 * second consumer that wants a stage-before-publish step.
 */

export type AiPromptLabel = 'production' | 'staging';

/** One row on the prompt list page. */
export interface AiPromptSummary {
  name: string;
  productionVersion: number | null;
  latestVersion: number | null;
  updatedAt: string | null;
  updatedByName: string | null;
}

/** One immutable version, as it appears in the version history list. */
export interface AiPromptVersion {
  id: string;
  version: number;
  template: string;
  commitMessage: string | null;
  createdByName: string | null;
  createdAt: string | null;
  labels: AiPromptLabel[];
}

/** Full detail for one prompt name - the list of its versions + which
 *  version each label currently points at. */
export interface AiPromptDetail {
  name: string;
  /** Declared template variables, e.g. ["title", "participants"]. */
  variables: string[];
  labels: Record<AiPromptLabel, number | null>;
  /** Newest first. */
  versions: AiPromptVersion[];
}

export interface CreatePromptVersionInput {
  template: string;
  commitMessage: string;
}

export interface PublishPromptVersionInput {
  versionId: string;
  label: AiPromptLabel;
}
