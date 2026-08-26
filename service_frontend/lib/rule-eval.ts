/**
 * Client-side rule evaluator (sprint-3/01) - the UX mirror of the backend
 * `app/rule_engine/evaluator.py`. Drives the form renderer's conditional
 * visibility (facts namespace `answers.<fieldKey>`, D14); the SERVER remains
 * the boundary - it re-derives the visible set on submit. Semantics kept in
 * parity: fail closed uniformly (missing/null fact, garbage value, unknown
 * operator, over-deep tree → that node is false, never a throw), numeric
 * string coercion in `eq`, date-only `between` END bound inclusive of the
 * whole day.
 */

import { RULE_MAX_DEPTH, type RuleCondition, type RuleGroup } from '@/types/rules';

/** True when the tree passes. None/empty = true (unconditional). */
export function evaluateRules(
  tree: RuleGroup | null | undefined,
  facts: Record<string, unknown>,
): boolean {
  if (!tree || !tree.rules || tree.rules.length === 0) return true;
  return evalGroup(tree, facts, 1);
}

function evalGroup(node: RuleGroup, facts: Record<string, unknown>, depth: number): boolean {
  if (depth > RULE_MAX_DEPTH) return false; // fail closed
  const results = (node.rules ?? []).map((rule) =>
    rule.kind === 'group' ? evalGroup(rule, facts, depth + 1) : evalCondition(rule, facts),
  );
  return node.combinator === 'or' ? results.some(Boolean) : results.every(Boolean);
}

function evalCondition(node: RuleCondition, facts: Record<string, unknown>): boolean {
  try {
    const value = facts[node.fact];
    if (value === null || value === undefined) return false; // D5 - incl. negative ops

    let operand: unknown = node.value;
    if (node.valueKind === 'fact') {
      operand = facts[operand as string];
      if (operand === null || operand === undefined) return false;
    }
    return apply(node.operator, value, operand);
  } catch {
    return false; // fail closed, never throw (D5)
  }
}

function apply(operator: string, value: unknown, operand: unknown): boolean {
  switch (operator) {
    case 'eq':
      return eq(value, operand);
    case 'neq':
      return !eq(value, operand);
    case 'contains':
      return String(value).toLowerCase().includes(String(operand).toLowerCase());
    case 'in':
      return asList(operand).some((item) => eq(value, item));
    case 'not_in':
      return !asList(operand).some((item) => eq(value, item));
    case 'gt':
    case 'gte':
    case 'lt':
    case 'lte': {
      const [left, right] = comparablePair(value, operand);
      if (operator === 'gt') return left > right;
      if (operator === 'gte') return left >= right;
      if (operator === 'lt') return left < right;
      return left <= right;
    }
    case 'between': {
      const [low, high] = asList(operand);
      const [left, lo] = comparablePair(value, low);
      let [, hi] = comparablePair(value, high);
      // Date-only END bound is inclusive of the whole day (backend parity).
      if (isDateComparison(value, high) && isDateOnly(high)) {
        hi = hi + 24 * 60 * 60 * 1000 - 1;
      }
      return lo <= left && left <= hi;
    }
    case 'before':
      return asTime(value) < asTime(operand);
    case 'after':
      return asTime(value) > asTime(operand);
    // Truthiness, matching the backend's `bool(value)` (note: any non-empty
    // string - including "false" - is truthy on both sides).
    case 'is_true':
      return Boolean(value) === true;
    case 'is_false':
      return Boolean(value) === false;
    case 'contains_any':
      return intersects(strSet(value), strSet(asList(operand)));
    case 'contains_all':
      return isSubset(strSet(asList(operand)), strSet(value));
    case 'not_contains':
      return !intersects(strSet(value), strSet(asList(operand)));
    default:
      return false; // unknown operator - fail closed
  }
}

// ---- coercion helpers (backend parity) ----

function eq(a: unknown, b: unknown): boolean {
  const num = maybeNumber(a);
  if (num !== null) {
    const other = maybeNumber(b);
    return other !== null && num === other;
  }
  return String(a) === String(b);
}

function maybeNumber(x: unknown): number | null {
  if (typeof x === 'boolean') return null;
  if (typeof x === 'number') return Number.isFinite(x) ? x : null;
  if (typeof x === 'string' && x.trim() !== '') {
    const n = Number(x);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/** (value, operand) as numbers, else as epoch millis. Throws on garbage -
 * the caller fails closed. */
function comparablePair(value: unknown, operand: unknown): [number, number] {
  const left = maybeNumber(value);
  const right = maybeNumber(operand);
  if (left !== null && right !== null) return [left, right];
  return [asTime(value), asTime(operand)];
}

function asTime(x: unknown): number {
  if (typeof x !== 'string' && !(x instanceof Date)) throw new Error('not a datetime');
  const t = x instanceof Date ? x.getTime() : Date.parse(isDateOnly(x) ? `${x}T00:00:00Z` : x);
  if (Number.isNaN(t)) throw new Error('not a datetime');
  return t;
}

/** A wire value like '2026-01-31' (no time part). */
function isDateOnly(x: unknown): boolean {
  return typeof x === 'string' && x.length === 10 && /^\d{4}-\d{2}-\d{2}$/.test(x);
}

function isDateComparison(value: unknown, operand: unknown): boolean {
  return maybeNumber(value) === null || maybeNumber(operand) === null;
}

function asList(x: unknown): unknown[] {
  if (!Array.isArray(x)) throw new Error('expected a list value');
  return x;
}

function strSet(items: unknown): Set<string> {
  const list = Array.isArray(items) ? items : [items];
  return new Set(list.map((item) => String(item)));
}

function intersects(a: Set<string>, b: Set<string>): boolean {
  return Array.from(a).some((item) => b.has(item));
}

function isSubset(subset: Set<string>, superset: Set<string>): boolean {
  return Array.from(subset).every((item) => superset.has(item));
}
