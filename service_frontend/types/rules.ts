/**
 * Rule engine types (sprint-2/02) — mirrors the backend camelCase wire
 * contracts (app/rule_engine/schemas.py once Phase B lands). The condition
 * tree is stored AS-IS in each consumer's own JSON column (D1 — rule =
 * property, not entity); `status_transitions.conditions_json` is the first.
 */

export type RuleFactType =
  | 'string'
  | 'number'
  | 'boolean'
  | 'date'
  | 'enum'
  | 'list';

export type RuleOperator =
  // string / enum
  | 'eq'
  | 'neq'
  | 'contains'
  | 'in'
  | 'not_in'
  // number
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'between'
  // boolean
  | 'is_true'
  | 'is_false'
  // date
  | 'before'
  | 'after'
  // list
  | 'contains_any'
  | 'contains_all'
  | 'not_contains';

/**
 * Operators offered per fact type (plan D3 — nothing more, no regex).
 * KEEP IN SYNC with the backend: OPERATORS_BY_TYPE (app/rule_engine/
 * schemas.py) and the prose phrases (app/rule_engine/prose.py) — every
 * operator key must exist in all three tables.
 */
export const RULE_OPERATORS: Record<
  RuleFactType,
  { value: RuleOperator; label: string }[]
> = {
  string: [
    { value: 'eq', label: 'is' },
    { value: 'neq', label: 'is not' },
    { value: 'contains', label: 'contains' },
    { value: 'in', label: 'is any of' },
    { value: 'not_in', label: 'is none of' },
  ],
  number: [
    { value: 'eq', label: '=' },
    { value: 'neq', label: '≠' },
    { value: 'gt', label: '>' },
    { value: 'gte', label: '≥' },
    { value: 'lt', label: '<' },
    { value: 'lte', label: '≤' },
    { value: 'between', label: 'between' },
  ],
  boolean: [
    { value: 'is_true', label: 'is yes' },
    { value: 'is_false', label: 'is no' },
  ],
  date: [
    { value: 'before', label: 'before' },
    { value: 'after', label: 'after' },
    { value: 'between', label: 'between' },
  ],
  enum: [
    { value: 'eq', label: 'is' },
    { value: 'neq', label: 'is not' },
    { value: 'in', label: 'is any of' },
    { value: 'not_in', label: 'is none of' },
  ],
  list: [
    { value: 'contains_any', label: 'contains any of' },
    { value: 'contains_all', label: 'contains all of' },
    { value: 'not_contains', label: 'contains none of' },
  ],
};

/**
 * Scalar compare operators that may flip to cross-fact mode (D4 —
 * `between`/`contains`/list ops stay literal-only).
 */
export const CROSS_FACT_OPERATORS: ReadonlySet<RuleOperator> =
  new Set<RuleOperator>([
    'eq',
    'neq',
    'gt',
    'gte',
    'lt',
    'lte',
    'before',
    'after',
  ]);

/** Groups nest to depth 5 (same guard as filter_translator / backend D3). */
export const RULE_MAX_DEPTH = 5;

export interface RuleFactOption {
  value: string;
  label: string;
}

/**
 * One whitelisted fact from the registry (D7) — `key` is namespaced by
 * source (`actor.name`, `record.slug`); the builder groups by `sourceLabel`.
 */
export interface RuleFact {
  key: string;
  label: string;
  type: RuleFactType;
  source: string;
  sourceLabel: string;
  /** Enum/list facts carry their selectable options. */
  options?: RuleFactOption[];
}

export type RuleValueKind = 'literal' | 'fact';

export interface RuleCondition {
  kind: 'condition';
  fact: string;
  operator: RuleOperator;
  /** `fact` ⇒ `value` is another fact key of the same type (D4). */
  valueKind: RuleValueKind;
  value: unknown;
}

export interface RuleGroup {
  kind: 'group';
  combinator: 'and' | 'or';
  rules: (RuleCondition | RuleGroup)[];
}

/** One row on the read-only Rules observability list (D12). */
export interface RuleSiteRow {
  /** Registry key of the consuming site (e.g. `status_transition`). */
  site: string;
  siteLabel: string;
  /** Where exactly — e.g. "Tenant · Active → Suspended". */
  context: string;
  /** Human prose rendering of the condition tree. */
  summary: string;
  /**
   * Site-specific locator (entity type for status_transition) — the
   * FRONTEND maps (site, target) to its deep-link route; the backend never
   * hardcodes frontend paths (code-review fix).
   */
  target: string;
  updatedAt: string | null;
}
