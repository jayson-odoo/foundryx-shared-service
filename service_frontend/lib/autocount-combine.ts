/**
 * Combine-rows editor helpers (sprint-5/10, R11/AC-10-76..82) - pure, no
 * React, no fetch.
 *
 * `simulateCombine` is now a PHASE 1 MOCK-ONLY helper (sprint-5/10 S5b-FE
 * review round 4 SF-4): `services/autocount-service.mock.ts`'s
 * `previewHttp` runs it over the mock's own sample rows to fold the SAME
 * six funnel counts the real backend returns (`AutocountCombinePreviewResult`,
 * `types/autocount.ts`) into its response - the Combine editor itself no
 * longer calls this directly, it only ever renders the funnel the SERVER
 * (real or mocked) sent back. Every formula still goes through the ONE
 * hand-written engine (`evaluateFormula`, never `eval`) - the house
 * anti-SSTI line applied to this surface too, exactly as it is server-side.
 */
import { evaluateFormula, resultToJson } from '@/lib/autocount-formula';
import type { AutocountCombineConfig, AutocountCombineDropStat } from '@/types/autocount';

/**
 * `simulateCombine`'s own full computation result - PHASE 1 MOCK internal
 * only, NOT the wire shape (that is `AutocountCombinePreviewResult`,
 * `types/autocount.ts`, reconciled to the server's flat `droppedByRule`
 * counts). The mock's `previewHttp` condenses `dropped`/`excludedRows` away
 * before returning, so this richer internal shape never leaks past it.
 */
export interface AutocountCombineSimulateResult {
  rowsIn: number;
  excludedCount: number;
  excludedRows: Array<Record<string, unknown>>;
  groups: number;
  dropped: Record<string, AutocountCombineDropStat>;
  roundedCount: number;
  rowsOut: number;
  rows: Array<Record<string, unknown>>;
}

export const MAX_COMPUTED = 10;
export const MAX_REQUIRE = 10;
export const MAX_GROUP_BY = 5;
export const MAX_MEASURES = 10;
export const MAX_DROP_RULES = 10;
export const MAX_CARRY = 20;

/** A fresh, empty combine config - the Combine rows section's starting point. */
export function emptyCombine(): AutocountCombineConfig {
  return { computed: [], require: [], measure: '', groupBy: [], measures: [], carry: [], round: [], drop: [] };
}

function truthy(value: unknown): boolean {
  return value !== null && value !== undefined && value !== false && value !== 0 && value !== '';
}

function roundHalfUp(value: number, dp: number): number {
  const factor = 10 ** dp;
  return Math.round((value + Number.EPSILON) * factor) / factor;
}

/**
 * Run the configured steps over a SAMPLE of rows (client-side, PHASE 1
 * MOCK). Never throws - a formula fault is folded into the funnel the same
 * way the real engine will (an exclusion / a named drop-rule error), so the
 * Test button always renders something rather than crashing the tab.
 */
export function simulateCombine(
  sampleRows: Array<Record<string, unknown>>,
  config: AutocountCombineConfig,
): AutocountCombineSimulateResult {
  const rowsIn = sampleRows.length;
  const excludedRows: Array<Record<string, unknown>> = [];
  let excludedCount = 0;

  type Row = Record<string, unknown>;
  const augmented: Row[] = [];

  for (const raw of sampleRows) {
    const row: Row = { ...raw };
    let excluded: { reason: string } | null = null;
    for (const step of config.computed) {
      if (!step.alias.trim() || !step.formula.trim()) continue;
      try {
        row[step.alias] = resultToJson(evaluateFormula(step.formula, null, row));
      } catch {
        // A computed column that cannot evaluate on this row leaves the
        // alias absent (mirrors the lookup-miss "absence, not None" rule) -
        // a downstream require/measure referencing it will itself fail
        // closed as an exclusion, never a silent zero.
      }
    }
    for (const rule of config.require) {
      if (!rule.formula.trim()) continue;
      try {
        if (!truthy(resultToJson(evaluateFormula(rule.formula, null, row)))) {
          excluded = { reason: rule.reason || rule.name };
          break;
        }
      } catch {
        excluded = { reason: 'require_error' };
        break;
      }
    }
    if (excluded) {
      excludedCount += 1;
      if (excludedRows.length < 50) {
        const entry: Row = { reason: excluded.reason };
        for (const col of config.groupBy) entry[col] = row[col];
        if (config.measure) entry[config.measure] = row[config.measure];
        excludedRows.push(entry);
      }
      continue;
    }
    augmented.push(row);
  }

  // Group, first-appearance order (deterministic for a fixed input).
  const groupKeyOf = (row: Row): string => config.groupBy.map((c) => String(row[c] ?? '')).join('\u0001');
  const groupOrder: string[] = [];
  const groups = new Map<string, Row[]>();
  for (const row of augmented) {
    const key = groupKeyOf(row);
    if (!groups.has(key)) {
      groups.set(key, []);
      groupOrder.push(key);
    }
    groups.get(key)?.push(row);
  }

  let roundedCount = 0;
  let outputRows: Row[] = groupOrder.map((key) => {
    const members = groups.get(key) ?? [];
    const out: Row = {};
    for (const col of config.groupBy) out[col] = members[0]?.[col];
    for (const carry of config.carry) out[carry] = members[0]?.[carry];
    for (const m of config.measures) {
      const values = members
        .map((r) => r[m.source])
        .filter((v) => v !== null && v !== undefined && v !== '');
      const numeric = values.map((v) => Number(v)).filter((n) => Number.isFinite(n));
      let value: number | string | null = null;
      if (m.op === 'count') value = values.length;
      else if (m.op === 'first') value = (values[0] as string | number) ?? null;
      else if (m.op === 'last') value = (values[values.length - 1] as string | number) ?? null;
      else if (m.op === 'sum') value = numeric.reduce((a, b) => a + b, 0);
      else if (m.op === 'min') value = numeric.length ? Math.min(...numeric) : null;
      else if (m.op === 'max') value = numeric.length ? Math.max(...numeric) : null;
      out[m.alias] = value;
    }
    for (const r of config.round) {
      if (r.mode !== 'half_up') continue;
      const current = out[r.measure];
      if (typeof current !== 'number') continue;
      const rounded = roundHalfUp(current, r.dp);
      if (rounded !== current) roundedCount += 1;
      out[r.measure] = rounded;
    }
    return out;
  });

  const dropped: Record<string, AutocountCombineDropStat> = {};
  for (const rule of config.drop) {
    dropped[rule.name] = { count: 0, rows: rule.listRows ? [] : undefined };
  }
  const kept: Row[] = [];
  for (const row of outputRows) {
    let droppedBy: string | null = null;
    for (const rule of config.drop) {
      if (!rule.formula.trim()) continue;
      try {
        if (truthy(resultToJson(evaluateFormula(rule.formula, null, row)))) {
          droppedBy = rule.name;
          break;
        }
      } catch {
        droppedBy = rule.name;
        break;
      }
    }
    if (droppedBy) {
      const stat = dropped[droppedBy] ?? { count: 0 };
      stat.count += 1;
      if (dropRuleListsRows(config, droppedBy) && stat.rows && stat.rows.length < 50) stat.rows.push(row);
      dropped[droppedBy] = stat;
      continue;
    }
    kept.push(row);
  }
  outputRows = kept;

  return {
    rowsIn,
    excludedCount,
    excludedRows,
    groups: groupOrder.length,
    dropped,
    roundedCount,
    rowsOut: outputRows.length,
    rows: outputRows,
  };
}

function dropRuleListsRows(config: AutocountCombineConfig, name: string): boolean {
  return Boolean(config.drop.find((r) => r.name === name)?.listRows);
}
