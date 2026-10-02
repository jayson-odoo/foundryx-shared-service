'use client';

import { useMemo, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import type {
  AutocountCombineConfig,
  AutocountCombineMeasureOp,
  AutocountCombinePreviewResult,
  AutocountFormulaTestResult,
} from '@/types/autocount';
import { emptyCombine } from '@/lib/autocount-combine';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import {
  AutocountFormulaBuilder,
  type FormulaVariableGroup,
} from '@/components/platform/autocount/formula-builder';
import { ClampedText } from '@/components/platform/clamped-text';
import { MultiSelect } from '@/components/platform/multi-select';
import { SearchSelect } from '@/components/platform/search-select';

const MEASURE_OPS: { label: string; value: AutocountCombineMeasureOp }[] = [
  { label: 'Sum', value: 'sum' },
  { label: 'Min', value: 'min' },
  { label: 'Max', value: 'max' },
  { label: 'Count', value: 'count' },
  { label: 'First', value: 'first' },
  { label: 'Last', value: 'last' },
];

const ROUND_MODES: { label: string; value: 'none' | 'half_up' }[] = [
  { label: 'None', value: 'none' },
  { label: 'Half up', value: 'half_up' },
];

const toFormulaVariableItems = (names: string[]) =>
  names.filter(Boolean).map((c) => ({ label: c, token: c }));

export interface CombineEditorProps {
  editing: boolean;
  combine: AutocountCombineConfig | null | undefined;
  onChange: (combine: AutocountCombineConfig | null) => void;
  /** Source columns + lookup aliases - what a computed formula, a require
   * rule, a group-by pick or a measure source may name (PRE-combine only -
   * the caller derives this from the task's own raw+lookup result columns,
   * never the last Test's possibly-COMBINED response columns). */
  columnOptions: string[];
  /** The Source tab's own Test button's SERVER funnel (AC-10-82, sprint-5/10
   * S5a) - `null` until a Test that carried this `combine` block has landed
   * a response. The combined rows themselves render in the Source tab's
   * existing preview grid, not here. */
  funnel: AutocountCombinePreviewResult | null;
  onServerTest: (
    formula: string,
    value: unknown,
  ) => Promise<AutocountFormulaTestResult>;
}

/**
 * The Source tab's Combine rows section (R11, AC-10-82) - one bounded,
 * operator-configurable step: computed columns, require rules, group-by
 * with measures and carried columns, per-measure rounding, ordered drop
 * rules. The funnel it renders comes from the SERVER (the Source tab's own
 * "Test" button, above, sends `combine` and passes the response down as the
 * `funnel` prop) - this editor never runs its own preview.
 */
export function CombineEditor({
  editing,
  combine,
  onChange,
  columnOptions,
  funnel,
  onServerTest,
}: CombineEditorProps) {
  const enabled = Boolean(combine);
  const config = combine ?? emptyCombine();
  const [formulaTarget, setFormulaTarget] = useState<
    | { kind: 'computed'; index: number }
    | { kind: 'require'; index: number }
    | { kind: 'drop'; index: number }
    | null
  >(null);

  const computedAliases = config.computed.map((c) => c.alias).filter(Boolean);
  const measureAliases = config.measures.map((m) => m.alias).filter(Boolean);
  const allColumnOptions = useMemo(
    () => Array.from(new Set([...columnOptions, ...computedAliases])),
    [columnOptions, computedAliases],
  );
  const groupOptions = useMemo(
    () => allColumnOptions.map((c) => ({ label: c, value: c })),
    [allColumnOptions],
  );
  const measureSourceOptions = allColumnOptions.map((c) => ({
    label: c,
    value: c,
  }));
  const measureAliasOptions = measureAliases.map((c) => ({
    label: c,
    value: c,
  }));
  // AC-10-82 fix (review round 2) - the designated measure (`combine.measure`)
  // is a PRE-GROUP column (validator: `combine.py` ~line 501, R11 ruling 2),
  // so `measureAliasOptions` (post-group aliases) was always the wrong set -
  // that part saves clean but 422s. Narrower than "any pre-group column",
  // though: the RUNTIME contract (`excluded_row_for_mapping_failure`,
  // `combine.py:966-978`) resolves the designated measure's grouped value by
  // finding the `measures[]` entry whose `source` IS `combine.measure` and
  // reading that entry's alias off the post-group row - a pick that is not a
  // declared `measures[].source` saves clean but reads back `measure: null`
  // in every exclusion entry (and the mapping's own dropped-row funnel), and
  // a non-numeric pick silently inflates `excludedNonzeroCount`
  // (`combine.py:944`, "not exactly 0" fails closed). So: once at least one
  // measure declares a non-empty `source`, only offer THOSE sources (in
  // pre-group column order) - never a pre-group column no measure reads from.
  // Only fall back to the full pre-group set when no measure has a source
  // yet (nothing to narrow to). Legacy configs may still carry a value
  // outside the offered set - keep it visible rather than blanking.
  const designatedMeasureOptions = useMemo(() => {
    const declaredSources = new Set(
      config.measures.map((m) => m.source).filter((s): s is string => Boolean(s)),
    );
    const base =
      declaredSources.size > 0
        ? groupOptions.filter((o) => declaredSources.has(o.value))
        : groupOptions;
    if (config.measure && !base.some((o) => o.value === config.measure)) {
      return [...base, { label: config.measure, value: config.measure }];
    }
    return base;
  }, [groupOptions, config.measures, config.measure]);

  const update = (patch: Partial<AutocountCombineConfig>) =>
    onChange({ ...config, ...patch });

  const openFormula =
    formulaTarget?.kind === 'computed'
      ? config.computed[formulaTarget.index]?.formula
      : formulaTarget?.kind === 'require'
        ? config.require[formulaTarget.index]?.formula
        : formulaTarget?.kind === 'drop'
          ? config.drop[formulaTarget.index]?.formula
          : '';

  // AC-10-76/77/79 (S5b-FE defect 1) - each combine formula only sees the
  // names it is allowed to reference, NEVER the same flat set for every
  // stage: `computed[i]` = raw/lookup columns + EARLIER computed aliases
  // only (a forward reference is the save-time 422); `require[i]` = raw/
  // lookup columns + ALL computed aliases (require runs after every
  // computed step); `drop[i]` runs AFTER grouping, so it may name ONLY the
  // post-group columns - `groupBy` + `carry` + `measures[].alias` - never a
  // raw/lookup/computed name that was not carried or grouped. Groups always
  // render (even empty) so the dialog stays in this multi-variable mode -
  // no combine formula ever uses the single-`value` transform model.
  const formulaVariableGroups = useMemo<FormulaVariableGroup[] | undefined>(() => {
    if (!formulaTarget) return undefined;
    // Confirm round 2 (S1) - `columnOptions` arrives from the Source tab's
    // `preCombineColumns`, which by backend design ALREADY carries every
    // computed alias once a combine-carrying Test has landed. The `Columns`
    // group is raw/lookup names only, so the ordered `Computed columns`
    // group below stays the single authority on which computed aliases a
    // stage may reference (without this, `computed[0]` was offered its own
    // alias and every LATER one - both save-time 422s).
    const sourceColumns = columnOptions.filter((c) => !computedAliases.includes(c));
    if (formulaTarget.kind === 'computed') {
      return [
        { label: 'Columns', items: toFormulaVariableItems(sourceColumns) },
        {
          label: 'Computed columns',
          items: toFormulaVariableItems(computedAliases.slice(0, formulaTarget.index)),
        },
      ];
    }
    if (formulaTarget.kind === 'require') {
      return [
        { label: 'Columns', items: toFormulaVariableItems(sourceColumns) },
        { label: 'Computed columns', items: toFormulaVariableItems(computedAliases) },
      ];
    }
    return [
      { label: 'Group by', items: toFormulaVariableItems(config.groupBy) },
      { label: 'Carry', items: toFormulaVariableItems(config.carry) },
      { label: 'Measures', items: toFormulaVariableItems(measureAliases) },
    ];
  }, [formulaTarget, columnOptions, computedAliases, config.groupBy, config.carry, measureAliases]);

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border p-4">
      <div className="flex items-center justify-between gap-2">
        <Label className="text-sm font-semibold">Combine rows</Label>
        {editing && (
          <div className="flex items-center gap-2">
            <Switch
              checked={enabled}
              onCheckedChange={(checked) =>
                onChange(checked ? emptyCombine() : null)
              }
              aria-label="Enable combine rows"
              data-testid="combine-enable"
            />
          </div>
        )}
      </div>

      {!enabled ? (
        <p className="text-sm text-muted-foreground">
          No combine step configured.
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          {/* Computed columns */}
          <section className="flex flex-col gap-2">
            <Label className="text-xs text-muted-foreground">
              Computed columns
            </Label>
            {config.computed.map((step, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <Input
                  value={step.alias}
                  onChange={(e) =>
                    update({
                      computed: config.computed.map((s, j) =>
                        j === i ? { ...s, alias: e.target.value } : s,
                      ),
                    })
                  }
                  disabled={!editing}
                  placeholder="item_code"
                  className="w-40 font-mono"
                  aria-label={`Computed column ${i + 1} alias`}
                />
                <ClampedText
                  text={step.formula || '-'}
                  lines={1}
                  className="max-w-md flex-1 rounded-md border border-border bg-muted/30 px-3 py-2 font-mono text-xs"
                />
                {editing && (
                  <>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        setFormulaTarget({ kind: 'computed', index: i })
                      }
                    >
                      Edit formula
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      mode="icon"
                      onClick={() =>
                        update({
                          computed: config.computed.filter((_, j) => j !== i),
                        })
                      }
                      aria-label={`Remove computed column ${i + 1}`}
                    >
                      <Trash2 className="size-3.5 text-destructive" />
                    </Button>
                  </>
                )}
              </div>
            ))}
            {editing && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-fit"
                onClick={() =>
                  update({
                    computed: [...config.computed, { alias: '', formula: '' }],
                  })
                }
              >
                <Plus className="size-3.5" />
                Add computed column
              </Button>
            )}
          </section>

          {/* Require rules */}
          <section className="flex flex-col gap-2">
            <Label className="text-xs text-muted-foreground">
              Require rules
            </Label>
            {config.require.map((rule, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <Input
                  value={rule.name}
                  onChange={(e) =>
                    update({
                      require: config.require.map((r, j) =>
                        j === i ? { ...r, name: e.target.value } : r,
                      ),
                    })
                  }
                  disabled={!editing}
                  placeholder="uom_rate"
                  className="w-40 font-mono"
                  aria-label={`Require rule ${i + 1} name`}
                />
                <ClampedText
                  text={rule.formula || '-'}
                  lines={1}
                  className="max-w-sm flex-1 rounded-md border border-border bg-muted/30 px-3 py-2 font-mono text-xs"
                />
                <Input
                  value={rule.reason}
                  onChange={(e) =>
                    update({
                      require: config.require.map((r, j) =>
                        j === i ? { ...r, reason: e.target.value } : r,
                      ),
                    })
                  }
                  disabled={!editing}
                  placeholder="uom_rate_unresolved"
                  className="w-52 font-mono"
                  aria-label={`Require rule ${i + 1} reason`}
                />
                {editing && (
                  <>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        setFormulaTarget({ kind: 'require', index: i })
                      }
                    >
                      Edit formula
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      mode="icon"
                      onClick={() =>
                        update({
                          require: config.require.filter((_, j) => j !== i),
                        })
                      }
                      aria-label={`Remove require rule ${i + 1}`}
                    >
                      <Trash2 className="size-3.5 text-destructive" />
                    </Button>
                  </>
                )}
              </div>
            ))}
            {editing && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-fit"
                onClick={() =>
                  update({
                    require: [
                      ...config.require,
                      { name: '', formula: '', reason: '' },
                    ],
                  })
                }
              >
                <Plus className="size-3.5" />
                Add require rule
              </Button>
            )}
          </section>

          {/* Group by / measure / carry */}
          <section className="grid gap-3 md:grid-cols-3">
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">Group by</Label>
              {editing ? (
                <MultiSelect
                  options={groupOptions}
                  value={config.groupBy}
                  onChange={(groupBy) => update({ groupBy })}
                  size="sm"
                  placeholder="Pick columns"
                />
              ) : (
                <span className="text-sm">
                  {config.groupBy.join(', ') || '-'}
                </span>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">Carry</Label>
              {editing ? (
                <MultiSelect
                  options={groupOptions}
                  value={config.carry}
                  onChange={(carry) => update({ carry })}
                  size="sm"
                  placeholder="Pick columns"
                />
              ) : (
                <span className="text-sm">
                  {config.carry.join(', ') || '-'}
                </span>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">
                Designated measure
              </Label>
              <SearchSelect
                options={designatedMeasureOptions}
                value={config.measure}
                onChange={(measure) => update({ measure })}
                placeholder="Pick a measure"
                disabled={!editing || designatedMeasureOptions.length === 0}
                ariaLabel="Designated measure"
              />
            </div>
          </section>

          <section className="flex flex-col gap-2">
            <Label className="text-xs text-muted-foreground">Measures</Label>
            {config.measures.map((m, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <SearchSelect
                  options={measureSourceOptions}
                  value={m.source}
                  onChange={(source) =>
                    update({
                      measures: config.measures.map((x, j) =>
                        j === i ? { ...x, source } : x,
                      ),
                    })
                  }
                  placeholder="Source column"
                  disabled={!editing}
                  ariaLabel="Measure source"
                  className="min-w-40"
                />
                <SearchSelect
                  options={MEASURE_OPS}
                  value={m.op}
                  onChange={(op) =>
                    update({
                      measures: config.measures.map((x, j) =>
                        j === i
                          ? { ...x, op: op as AutocountCombineMeasureOp }
                          : x,
                      ),
                    })
                  }
                  disabled={!editing}
                  ariaLabel="Measure operation"
                  className="min-w-32"
                />
                <span className="text-xs text-muted-foreground">as</span>
                <Input
                  value={m.alias}
                  onChange={(e) =>
                    update({
                      measures: config.measures.map((x, j) =>
                        j === i ? { ...x, alias: e.target.value } : x,
                      ),
                    })
                  }
                  disabled={!editing}
                  placeholder="qty"
                  className="w-36 font-mono"
                  aria-label={`Measure ${i + 1} alias`}
                />
                {editing && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    mode="icon"
                    onClick={() =>
                      update({
                        measures: config.measures.filter((_, j) => j !== i),
                      })
                    }
                    aria-label={`Remove measure ${i + 1}`}
                  >
                    <Trash2 className="size-3.5 text-destructive" />
                  </Button>
                )}
              </div>
            ))}
            {editing && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-fit"
                onClick={() =>
                  update({
                    measures: [
                      ...config.measures,
                      { source: '', op: 'sum', alias: '' },
                    ],
                  })
                }
              >
                <Plus className="size-3.5" />
                Add measure
              </Button>
            )}
          </section>

          {/* Rounding */}
          <section className="flex flex-col gap-2">
            <Label className="text-xs text-muted-foreground">Rounding</Label>
            {config.round.map((r, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <SearchSelect
                  options={measureAliasOptions}
                  value={r.measure}
                  onChange={(measure) =>
                    update({
                      round: config.round.map((x, j) =>
                        j === i ? { ...x, measure } : x,
                      ),
                    })
                  }
                  placeholder="Measure"
                  disabled={!editing}
                  ariaLabel="Round measure"
                  className="min-w-36"
                />
                <SearchSelect
                  options={ROUND_MODES}
                  value={r.mode}
                  onChange={(mode) =>
                    update({
                      round: config.round.map((x, j) =>
                        j === i
                          ? { ...x, mode: mode as 'none' | 'half_up' }
                          : x,
                      ),
                    })
                  }
                  disabled={!editing}
                  ariaLabel="Round mode"
                  className="min-w-32"
                />
                <Input
                  type="number"
                  min={0}
                  max={6}
                  value={r.dp}
                  onChange={(e) =>
                    update({
                      round: config.round.map((x, j) =>
                        j === i ? { ...x, dp: Number(e.target.value) || 0 } : x,
                      ),
                    })
                  }
                  disabled={!editing}
                  className="w-20"
                  aria-label={`Round ${i + 1} decimal places`}
                />
                {editing && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    mode="icon"
                    onClick={() =>
                      update({ round: config.round.filter((_, j) => j !== i) })
                    }
                    aria-label={`Remove rounding rule ${i + 1}`}
                  >
                    <Trash2 className="size-3.5 text-destructive" />
                  </Button>
                )}
              </div>
            ))}
            {editing && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-fit"
                onClick={() =>
                  update({
                    round: [
                      ...config.round,
                      { measure: '', mode: 'half_up', dp: 0 },
                    ],
                  })
                }
              >
                <Plus className="size-3.5" />
                Add rounding rule
              </Button>
            )}
          </section>

          {/* Drop rules */}
          <section className="flex flex-col gap-2">
            <Label className="text-xs text-muted-foreground">Drop rules</Label>
            {config.drop.map((rule, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <Input
                  value={rule.name}
                  onChange={(e) =>
                    update({
                      drop: config.drop.map((r, j) =>
                        j === i ? { ...r, name: e.target.value } : r,
                      ),
                    })
                  }
                  disabled={!editing}
                  placeholder="zero"
                  className="w-32 font-mono"
                  aria-label={`Drop rule ${i + 1} name`}
                />
                <ClampedText
                  text={rule.formula || '-'}
                  lines={1}
                  className="max-w-sm flex-1 rounded-md border border-border bg-muted/30 px-3 py-2 font-mono text-xs"
                />
                {editing && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setFormulaTarget({ kind: 'drop', index: i })}
                  >
                    Edit formula
                  </Button>
                )}
                <div className="flex items-center gap-1.5">
                  <Switch
                    checked={Boolean(rule.listRows)}
                    onCheckedChange={(listRows) =>
                      update({
                        drop: config.drop.map((r, j) =>
                          j === i ? { ...r, listRows } : r,
                        ),
                      })
                    }
                    disabled={!editing}
                    aria-label={`List dropped rows for ${rule.name || `rule ${i + 1}`}`}
                    data-testid={`drop-list-rows-${i}`}
                  />
                  <span className="text-xs text-muted-foreground">
                    List dropped rows
                  </span>
                </div>
                {editing && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    mode="icon"
                    onClick={() =>
                      update({ drop: config.drop.filter((_, j) => j !== i) })
                    }
                    aria-label={`Remove drop rule ${i + 1}`}
                  >
                    <Trash2 className="size-3.5 text-destructive" />
                  </Button>
                )}
              </div>
            ))}
            {editing && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-fit"
                onClick={() =>
                  update({
                    drop: [
                      ...config.drop,
                      { name: '', formula: '', listRows: false },
                    ],
                  })
                }
              >
                <Plus className="size-3.5" />
                Add drop rule
              </Button>
            )}
          </section>

          {funnel && (
            <div
              className="flex flex-wrap items-center gap-1.5"
              data-testid="combine-funnel"
            >
              <Badge variant="secondary" appearance="light" size="sm">
                {funnel.rowsIn} in
              </Badge>
              <Badge variant="warning" appearance="light" size="sm">
                {funnel.excludedCount} excluded
              </Badge>
              <Badge variant="info" appearance="light" size="sm">
                {funnel.groups} groups
              </Badge>
              {Object.entries(funnel.droppedByRule).map(([name, count]) => (
                <Badge
                  key={name}
                  variant="secondary"
                  appearance="light"
                  size="sm"
                >
                  {name}: {count} dropped
                </Badge>
              ))}
              <Badge variant="success" appearance="light" size="sm">
                {funnel.rowsOut} out
              </Badge>
            </div>
          )}
        </div>
      )}

      <AutocountFormulaBuilder
        open={formulaTarget !== null}
        onOpenChange={(open) => {
          if (!open) setFormulaTarget(null);
        }}
        value={openFormula ?? ''}
        onApply={(formula) => {
          if (!formulaTarget) return;
          if (formulaTarget.kind === 'computed') {
            update({
              computed: config.computed.map((s, j) =>
                j === formulaTarget.index ? { ...s, formula } : s,
              ),
            });
          } else if (formulaTarget.kind === 'require') {
            update({
              require: config.require.map((r, j) =>
                j === formulaTarget.index ? { ...r, formula } : r,
              ),
            });
          } else {
            update({
              drop: config.drop.map((r, j) =>
                j === formulaTarget.index ? { ...r, formula } : r,
              ),
            });
          }
        }}
        onServerTest={onServerTest}
        variables={formulaVariableGroups}
      />
    </div>
  );
}
