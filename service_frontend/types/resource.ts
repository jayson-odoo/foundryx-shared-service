/**
 * Generic "Resource" types - the contract shared by every list/form in the
 * system. The Resource shell (components/platform) and every entity service
 * (users, and future entities) speak this language so the design + data
 * patterns are replicable. See documentation/plans/sprint-1/02-user-management.md.
 */

/** A single filter leaf: one whitelisted field, one operator, a value. */
export interface FilterCondition {
  kind: 'condition';
  field: string;
  operator: FilterOperator;
  value: FilterValue;
}

/** A nested group combining conditions/sub-groups with AND or OR. */
export interface FilterGroup {
  kind: 'group';
  combinator: 'and' | 'or';
  rules: FilterRule[];
}

export type FilterRule = FilterCondition | FilterGroup;

export type FilterValue = string | number | boolean | null | string[];

export type FilterOperator =
  | 'contains'
  | 'eq'
  | 'neq'
  | 'in'
  | 'between'
  | 'before'
  | 'after'
  | 'is_true'
  | 'is_false';

/** Field types drive which operators + input control the filter builder shows. */
export type FilterFieldType = 'text' | 'enum' | 'date' | 'bool';

/** A field a list declares as filterable (whitelist enforced server-side too). */
export interface FilterFieldDef {
  field: string;
  label: string;
  type: FilterFieldType;
  /** For `enum` fields: the selectable options. */
  options?: { label: string; value: string }[];
}

/** Which records are in scope (soft-trash aware). */
export type StatusView = 'active' | 'trashed';

/** Sort directive - column id + direction. */
export interface SortState {
  id: string;
  desc: boolean;
}

/** The full query a list issues to its service (server-side semantics). */
export interface ListQuery {
  page: number; // 0-based page index
  pageSize: number;
  search?: string;
  sort?: SortState | null;
  filter?: FilterGroup | null;
  statusView?: StatusView;
  /**
   * Generic N-way segment (entities with more views than Active|Trashed -
   * e.g. the email log's All|Pending|Sent|Failed|Cancelled). Mutually
   * exclusive with statusView; configured via ResourceListConfig.segments.
   */
  segment?: string;
}

/** The page a service returns. `total` = rows matching the query (all pages). */
export interface ListResult<T> {
  data: T[];
  total: number;
  page: number;
}

/**
 * Per-user, per-view column preferences (resize / order / visibility),
 * persisted by `view_key` (e.g. 'users.list'). Phase A is mock-backed;
 * Phase B persists to the backend `user_view_preferences` table.
 */
export interface ViewPreferences {
  order: string[]; // column ids, in display order
  widths: Record<string, number>; // column id -> px width
  hidden: string[]; // hidden column ids
}
