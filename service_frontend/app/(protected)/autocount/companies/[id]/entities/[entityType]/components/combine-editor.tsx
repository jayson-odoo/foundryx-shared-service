'use client';

import { useMemo, useState } from 'react';
import { Play, Plus, Trash2 } from 'lucide-react';
import type {
  AutocountCombineConfig,
  AutocountCombineMeasureOp,
  AutocountFormulaTestResult,
} from '@/types/autocount';
import { emptyCombine, simulateCombine } from '@/lib/autocount-combine';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { AutocountFormulaBuilder } from '@/components/platform/autocount/formula-builder';
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

export interface CombineEditorProps {
  editing: boolean;
  combine: AutocountCombineConfig | null | undefined;
  onChange: (combine: AutocountCombineConfig | null) => void;
  /** Source columns + lookup aliases - what a computed formula, a require
   * rule, a group-by pick or a measure source may name. */
  columnOptions: string[];
  /** The combined Test's own sample rows (post-lookup), for the funnel. */
  sampleRows: Array<Record<string, unknown>>;
  onServerTest: (
    formula: string,
    value: unknown,
  ) => Promise<AutocountFormulaTestResult>;
}

/**
 * The Source tab's Combine rows section (R11, AC-10-82) - one bounded,
 * operator-configurable step: computed columns, require rules, group-by
 * with measures and carried columns, per-measure rounding, ordered drop
 * rules. A Test button runs the CLIENT-SIDE funnel simulator
 * (`lib/autocount-combine.ts`, PHASE 1 MOCK - the real engine lands S5a)
 * over the sample rows already on hand.
 */
export function CombineEditor({
  editing,
  combine,
  onChange,
  columnOptions,
  sampleRows,
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
  const [funnel, setFunnel] = useState<ReturnType<
    typeof simulateCombine
  > | null>(null);

  const computedAliases = config.computed.map((c) => c.alias).filter(Boolean);
  const measureAliases = config.measures.map((m) => m.alias).filter(Boolean);
  const allColumnOptions = useMemo(
    () => Array.from(new Set([...columnOptions, ...computedAliases])),
    [columnOptions, computedAliases],
  );
  const groupOptions = allColumnOptions.map((c) => ({ label: c, value: c }));
  const measureSourceOptions = allColumnOptions.map((c) => ({
    label: c,
    value: c,
  }));
  const measureAliasOptions = measureAliases.map((c) => ({
    label: c,
    value: c,
  }));

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
                options={measureAliasOptions}
                value={config.measure}
                onChange={(measure) => update({ measure })}
                placeholder="Pick a measure"
                disabled={!editing || measureAliasOptions.length === 0}
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

          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="primary"
              size="sm"
              onClick={() => setFunnel(simulateCombine(sampleRows, config))}
              disabled={sampleRows.length === 0}
              data-testid="combine-test"
            >
              <Play className="size-3.5" />
              Test
            </Button>
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
                {Object.entries(funnel.dropped).map(([name, stat]) => (
                  <Badge
                    key={name}
                    variant="secondary"
                    appearance="light"
                    size="sm"
                  >
                    {name}: {stat.count} dropped
                  </Badge>
                ))}
                <Badge variant="success" appearance="light" size="sm">
                  {funnel.rowsOut} out
                </Badge>
              </div>
            )}
          </div>
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
        variables={[
          {
            label: 'Columns',
            items: allColumnOptions.map((c) => ({ label: c, token: c })),
          },
        ]}
      />
    </div>
  );
}
