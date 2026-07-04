/**
 * Terminology types (sprint-3/08, F10) — mirror of the backend wire schemas.
 * The DB/code entity names are fixed; only these display labels are tenant-set.
 */

export interface TermLabels {
  singular: string;
  plural: string;
}

/** GET /terminology — merged map {entityKey: {singular, plural}}. */
export type TerminologyMap = Record<string, TermLabels>;

/** GET /terminology/catalog item — a registered TermDef + its current override. */
export interface TermCatalogItem {
  key: string;
  module: string;
  group: string | null;
  description: string | null;
  defaultSingular: string;
  defaultPlural: string;
  /** Present only when the tenant has overridden this key. */
  overrideSingular: string | null;
  overridePlural: string | null;
  /** Resolved (override-or-default) labels. */
  singular: string;
  plural: string;
}
