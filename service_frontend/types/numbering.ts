/**
 * Numbering types (sprint-4/07, Cluster F) — mirror of the backend wire schemas.
 * The DB/code doc-type names are fixed; only prefix / format / reset / next-val
 * are tenant-set per doc type.
 */

export type NumberReset = 'never' | 'yearly' | 'monthly';

export const NUMBER_RESET_OPTIONS: { value: NumberReset; label: string }[] = [
  { value: 'never', label: 'Never' },
  { value: 'yearly', label: 'Yearly' },
  { value: 'monthly', label: 'Monthly' },
];

/** GET /numbering item — a registered NumberSequenceDef + its current override. */
export interface NumberCatalogItem {
  docType: string;
  label: string;
  module: string;
  defaultPrefix: string;
  defaultFormat: string;
  defaultReset: NumberReset;
  /** Present only when the tenant has overridden this doc type. */
  overridePrefix: string | null;
  overrideFormat: string | null;
  overrideReset: NumberReset | null;
  /** Resolved (override-or-default) effective values. */
  prefix: string;
  formatPattern: string;
  reset: NumberReset;
  /** The next running number that will be handed out for the current period. */
  nextVal: number;
  /** A live sample of the next number that would be generated. */
  sample: string;
}

/** PUT /numbering/{docType} body — upsert a format override. */
export interface NumberFormatSet {
  prefix: string;
  formatPattern: string;
  reset: NumberReset;
}
