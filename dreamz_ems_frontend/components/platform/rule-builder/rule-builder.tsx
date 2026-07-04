'use client';

/**
 * RuleBuilder (sprint-2/02) — the reusable condition-tree builder over the
 * whitelisted fact registry. Sibling of resource-list/filter-builder (D9 —
 * same draft-tree interaction, its own types): facts grouped by source,
 * operators per fact type (D3), literal⇄fact cross-compare on scalar ops
 * (D4), AND/OR groups nesting to depth 5, stale-fact chips (D11).
 *
 * Mount-initialized: `value` seeds the draft; remount (key) to load another
 * tree. Emits the serialized RuleGroup on every edit — null when empty
 * (= unconditional).
 */
import { useMemo, useRef, useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  ArrowLeftRight,
  Plus,
  Trash2,
  Undo2,
} from 'lucide-react';
import {
  CROSS_FACT_OPERATORS,
  RULE_MAX_DEPTH,
  RULE_OPERATORS,
  type RuleCondition,
  type RuleFact,
  type RuleGroup,
  type RuleOperator,
} from '@/types/rules';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { MultiSelect } from '@/components/platform/multi-select';
import {
  SearchSelect,
  type SearchSelectGroup,
} from '@/components/platform/search-select';

/**
 * Comma-separated free-text multi value. Keeps the RAW text locally and
 * emits the parsed array (code-review fix: a controlled join/split round-trip
 * dropped a trailing comma every keystroke, blocking entry of a second value).
 */
function FreeFormMulti({
  selected,
  disabled,
  onChange,
}: {
  selected: string[];
  disabled: boolean;
  onChange: (value: string[]) => void;
}) {
  const [raw, setRaw] = useState(selected.join(', '));
  return (
    <Input
      className="h-8 w-48"
      placeholder="Comma-separated values"
      value={raw}
      disabled={disabled}
      onChange={(e) => {
        setRaw(e.target.value);
        onChange(
          e.target.value
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean),
        );
      }}
    />
  );
}

/** Icon-button wrapper with an explanatory hover tooltip (icons alone are
 * not self-explanatory — user feedback, sprint-2/02 iteration). */
function IconHint({ hint, children }: { hint: string; children: ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent className="max-w-64">{hint}</TooltipContent>
    </Tooltip>
  );
}

// ---- Internal draft tree (stable React key per node, like filter-builder) ----
interface DraftCondition {
  key: string;
  kind: 'condition';
  fact: string;
  operator: RuleOperator;
  valueKind: 'literal' | 'fact';
  value: unknown;
}
interface DraftGroup {
  key: string;
  kind: 'group';
  combinator: 'and' | 'or';
  rules: DraftRule[];
}
type DraftRule = DraftCondition | DraftGroup;

/** Which value widget an operator needs — value resets when the shape changes. */
type ValueShape = 'none' | 'single' | 'pair' | 'multi';

function shapeFor(operator: RuleOperator): ValueShape {
  if (operator === 'is_true' || operator === 'is_false') return 'none';
  if (operator === 'between') return 'pair';
  if (
    operator === 'in' ||
    operator === 'not_in' ||
    operator === 'contains_any' ||
    operator === 'contains_all' ||
    operator === 'not_contains'
  )
    return 'multi';
  return 'single';
}

function emptyValue(shape: ValueShape): unknown {
  if (shape === 'none') return null;
  if (shape === 'pair') return ['', ''];
  if (shape === 'multi') return [];
  return '';
}

function toWire(rule: DraftRule): RuleGroup | RuleCondition {
  if (rule.kind === 'group') {
    return {
      kind: 'group',
      combinator: rule.combinator,
      rules: rule.rules.map(toWire),
    };
  }
  return {
    kind: 'condition',
    fact: rule.fact,
    operator: rule.operator,
    valueKind: rule.valueKind,
    value: rule.value,
  };
}

function collectStale(group: DraftGroup, known: Set<string>): string[] {
  return group.rules.flatMap((r) =>
    r.kind === 'group'
      ? collectStale(r, known)
      : known.has(r.fact)
        ? []
        : [r.fact],
  );
}

export interface RuleBuilderProps {
  /** Whitelisted facts for this consumer's sources (GET /rule-facts). */
  facts: RuleFact[];
  /** Initial tree (null = unconditional). Remount to load a different one. */
  value: RuleGroup | null;
  /** Fires on every edit with the serialized tree — null when empty. */
  onChange: (group: RuleGroup | null) => void;
  disabled?: boolean;
}

export function RuleBuilder({
  facts,
  value,
  onChange,
  disabled = false,
}: RuleBuilderProps) {
  const keyRef = useRef(0);
  const nextKey = () => `k${++keyRef.current}`;

  const fromWire = (rule: RuleGroup | RuleCondition): DraftRule =>
    rule.kind === 'group'
      ? {
          key: nextKey(),
          kind: 'group',
          combinator: rule.combinator,
          rules: rule.rules.map(fromWire),
        }
      : { key: nextKey(), ...rule };

  const [root, setRoot] = useState<DraftGroup>(() =>
    value
      ? (fromWire(value) as DraftGroup)
      : { key: nextKey(), kind: 'group', combinator: 'and', rules: [] },
  );

  // Derived lookups memoized — rebuilt only when the registry changes, not
  // on every keystroke (code-review cleanup).
  const factByKey = useMemo(
    () => new Map(facts.map((f) => [f.key, f])),
    [facts],
  );
  const factGroups = useMemo<SearchSelectGroup[]>(() => {
    const groups: SearchSelectGroup[] = [];
    for (const fact of facts) {
      const group = groups.find((g) => g.label === fact.sourceLabel);
      const option = { value: fact.key, label: fact.label };
      if (group) group.options.push(option);
      else groups.push({ label: fact.sourceLabel, options: [option] });
    }
    return groups;
  }, [facts]);
  const stale = collectStale(root, new Set(factByKey.keys()));

  const newCondition = (): DraftCondition => {
    const first = facts[0];
    const operator = RULE_OPERATORS[first?.type ?? 'string'][0].value;
    return {
      key: nextKey(),
      kind: 'condition',
      fact: first?.key ?? '',
      operator,
      valueKind: 'literal',
      value: emptyValue(shapeFor(operator)),
    };
  };

  const update = (next: DraftGroup) => {
    setRoot(next);
    onChange(next.rules.length === 0 ? null : (toWire(next) as RuleGroup));
  };

  return (
    <div className="flex flex-col gap-2">
      {stale.length > 0 && (
        <div className="flex items-start gap-2 rounded-md border border-[var(--color-warning-soft,var(--color-yellow-200))] bg-[var(--color-warning-soft,var(--color-yellow-50))] p-2.5 text-xs text-[var(--color-warning-accent,var(--color-yellow-700))]">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <span>
            Some conditions reference fields that no longer exist — fix or
            remove them before saving.
          </span>
        </div>
      )}
      <GroupEditor
        group={root}
        depth={0}
        facts={facts}
        factByKey={factByKey}
        factGroups={factGroups}
        newCondition={newCondition}
        nextKey={nextKey}
        disabled={disabled}
        onChange={update}
      />
    </div>
  );
}

interface GroupEditorProps {
  group: DraftGroup;
  depth: number;
  facts: RuleFact[];
  factByKey: Map<string, RuleFact>;
  factGroups: SearchSelectGroup[];
  newCondition: () => DraftCondition;
  nextKey: () => string;
  disabled: boolean;
  onChange: (group: DraftGroup) => void;
  /** Removes THIS group from its parent — absent on the root. */
  onRemove?: () => void;
}

function GroupEditor({
  group,
  depth,
  facts,
  factByKey,
  factGroups,
  newCondition,
  nextKey,
  disabled,
  onChange,
  onRemove,
}: GroupEditorProps) {
  function updateRule(key: string, next: DraftRule | null) {
    onChange({
      ...group,
      rules: group.rules.flatMap((r) =>
        r.key === key ? (next ? [next] : []) : [r],
      ),
    });
  }

  return (
    <div
      className={cn(
        'flex flex-col gap-2 rounded-lg border border-border p-3',
        depth > 0 && 'bg-muted/40',
      )}
    >
      {(group.rules.length > 1 || depth > 0) && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Match</span>
          <ToggleGroup
            type="single"
            size="sm"
            value={group.combinator}
            onValueChange={(v) =>
              !disabled &&
              v &&
              onChange({ ...group, combinator: v as 'and' | 'or' })
            }
          >
            <ToggleGroupItem value="and" disabled={disabled}>
              AND
            </ToggleGroupItem>
            <ToggleGroupItem value="or" disabled={disabled}>
              OR
            </ToggleGroupItem>
          </ToggleGroup>
        </div>
      )}

      {group.rules.length === 0 && depth === 0 && (
        <p className="text-xs text-muted-foreground">
          No conditions — always allowed{disabled ? '.' : ' (add one below).'}
        </p>
      )}

      <div className="flex flex-col gap-2">
        {group.rules.map((rule) =>
          rule.kind === 'condition' ? (
            <ConditionRow
              key={rule.key}
              condition={rule}
              facts={facts}
              factByKey={factByKey}
              factGroups={factGroups}
              disabled={disabled}
              onChange={(next) => updateRule(rule.key, next)}
              onRemove={() => updateRule(rule.key, null)}
            />
          ) : (
            <GroupEditor
              key={rule.key}
              group={rule}
              depth={depth + 1}
              facts={facts}
              factByKey={factByKey}
              factGroups={factGroups}
              newCondition={newCondition}
              nextKey={nextKey}
              disabled={disabled}
              onChange={(next) => updateRule(rule.key, next)}
              onRemove={() => updateRule(rule.key, null)}
            />
          ),
        )}
      </div>

      {!disabled && (
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              onChange({ ...group, rules: [...group.rules, newCondition()] })
            }
          >
            <Plus /> Add condition
          </Button>
          {depth < RULE_MAX_DEPTH - 1 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() =>
                onChange({
                  ...group,
                  rules: [
                    ...group.rules,
                    {
                      key: nextKey(),
                      kind: 'group',
                      combinator: 'and',
                      rules: [newCondition()],
                    },
                  ],
                })
              }
            >
              <Plus /> Add group
            </Button>
          )}
          {onRemove && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="ms-auto text-muted-foreground"
              aria-label="Remove group"
              onClick={onRemove}
            >
              <Trash2 className="size-3.5" />
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

interface ConditionRowProps {
  condition: DraftCondition;
  facts: RuleFact[];
  factByKey: Map<string, RuleFact>;
  factGroups: SearchSelectGroup[];
  disabled: boolean;
  onChange: (next: DraftCondition) => void;
  onRemove: () => void;
}

function ConditionRow({
  condition,
  facts,
  factByKey,
  factGroups,
  disabled,
  onChange,
  onRemove,
}: ConditionRowProps) {
  const fact = factByKey.get(condition.fact);
  const type = fact?.type ?? 'string';
  const operators = RULE_OPERATORS[type];
  const crossable = CROSS_FACT_OPERATORS.has(condition.operator);

  const changeFact = (key: string) => {
    const next = factByKey.get(key);
    const operator = RULE_OPERATORS[next?.type ?? 'string'][0].value;
    onChange({
      ...condition,
      fact: key,
      operator,
      valueKind: 'literal',
      value: emptyValue(shapeFor(operator)),
    });
  };

  const changeOperator = (op: string) => {
    const operator = op as RuleOperator;
    const sameShape = shapeFor(operator) === shapeFor(condition.operator);
    const keepFactMode =
      condition.valueKind === 'fact' && CROSS_FACT_OPERATORS.has(operator);
    onChange({
      ...condition,
      operator,
      valueKind: keepFactMode ? 'fact' : 'literal',
      value:
        keepFactMode || sameShape
          ? condition.value
          : emptyValue(shapeFor(operator)),
    });
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      {fact ? (
        <SearchSelect
          className="w-44"
          groups={factGroups}
          value={condition.fact}
          onChange={changeFact}
          ariaLabel="Fact"
          searchPlaceholder="Search fields…"
          disabled={disabled}
        />
      ) : (
        <Badge variant="warning" appearance="light" className="h-8 px-2.5">
          <AlertTriangle className="size-3" /> Unknown field: {condition.fact}
        </Badge>
      )}

      {fact && (
        <SearchSelect
          className="w-36"
          options={operators.map((o) => ({ value: o.value, label: o.label }))}
          value={condition.operator}
          onChange={changeOperator}
          ariaLabel="Operator"
          searchPlaceholder="Search operators…"
          disabled={disabled}
        />
      )}

      {fact && condition.valueKind === 'fact' ? (
        <SearchSelect
          className="w-44"
          options={facts
            .filter((f) => f.type === type && f.key !== condition.fact)
            .map((f) => ({ value: f.key, label: f.label }))}
          value={typeof condition.value === 'string' ? condition.value : null}
          onChange={(value) => onChange({ ...condition, value })}
          ariaLabel="Compare fact"
          placeholder="Pick a field…"
          searchPlaceholder="Search fields…"
          disabled={disabled}
        />
      ) : (
        fact && (
          <ConditionValue
            condition={condition}
            fact={fact}
            disabled={disabled}
            onChange={onChange}
          />
        )
      )}

      {fact && crossable && !disabled && (
        <IconHint
          hint={
            condition.valueKind === 'fact'
              ? 'Switch back to typing a fixed value'
              : 'Compare with another field instead of a fixed value (e.g. Created at before Member since)'
          }
        >
          <Button
            type="button"
            variant="ghost"
            size="sm"
            mode="icon"
            aria-label={
              condition.valueKind === 'fact'
                ? 'Use literal value'
                : 'Compare to field'
            }
            onClick={() =>
              onChange({
                ...condition,
                valueKind: condition.valueKind === 'fact' ? 'literal' : 'fact',
                value:
                  condition.valueKind === 'fact'
                    ? emptyValue(shapeFor(condition.operator))
                    : null,
              })
            }
          >
            {condition.valueKind === 'fact' ? (
              <Undo2 className="size-3.5" />
            ) : (
              <ArrowLeftRight className="size-3.5" />
            )}
          </Button>
        </IconHint>
      )}

      {!disabled && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          mode="icon"
          aria-label="Remove condition"
          onClick={onRemove}
        >
          <Trash2 className="size-3.5 text-muted-foreground" />
        </Button>
      )}
    </div>
  );
}

function ConditionValue({
  condition,
  fact,
  disabled,
  onChange,
}: {
  condition: DraftCondition;
  fact: RuleFact;
  disabled: boolean;
  onChange: (next: DraftCondition) => void;
}) {
  const shape = shapeFor(condition.operator);
  if (shape === 'none') return null;

  const inputType =
    fact.type === 'number' ? 'number' : fact.type === 'date' ? 'date' : 'text';

  if (shape === 'pair') {
    const v = Array.isArray(condition.value)
      ? (condition.value as string[])
      : ['', ''];
    return (
      <div className="flex items-center gap-1">
        <Input
          type={inputType}
          className="h-8 w-32"
          value={v[0] ?? ''}
          disabled={disabled}
          onChange={(e) =>
            onChange({ ...condition, value: [e.target.value, v[1] ?? ''] })
          }
        />
        <span className="text-xs text-muted-foreground">and</span>
        <Input
          type={inputType}
          className="h-8 w-32"
          value={v[1] ?? ''}
          disabled={disabled}
          onChange={(e) =>
            onChange({ ...condition, value: [v[0] ?? '', e.target.value] })
          }
        />
      </div>
    );
  }

  if (shape === 'multi') {
    const selected = Array.isArray(condition.value)
      ? (condition.value as string[])
      : [];
    if (fact.options?.length) {
      return (
        <div className="min-w-44 flex-1">
          <MultiSelect
            options={fact.options}
            value={selected}
            onChange={(value) => onChange({ ...condition, value })}
            size="sm"
            placeholder="Select…"
            disabled={disabled}
          />
        </div>
      );
    }
    // Free-form multi (string in/not_in without options) — comma-separated.
    return (
      <FreeFormMulti
        selected={selected}
        disabled={disabled}
        onChange={(value) => onChange({ ...condition, value })}
      />
    );
  }

  // single
  if (fact.type === 'enum' && fact.options?.length) {
    return (
      <SearchSelect
        className="w-40"
        options={fact.options}
        value={typeof condition.value === 'string' ? condition.value : null}
        onChange={(value) => onChange({ ...condition, value })}
        ariaLabel="Value"
        placeholder="Select…"
        disabled={disabled}
      />
    );
  }
  if (fact.type === 'boolean') return null;

  return (
    <Input
      type={inputType}
      className={cn('h-8', inputType === 'date' ? 'w-36' : 'w-40')}
      placeholder="Value"
      value={
        typeof condition.value === 'string' ||
        typeof condition.value === 'number'
          ? String(condition.value)
          : ''
      }
      disabled={disabled}
      onChange={(e) =>
        onChange({
          ...condition,
          value:
            inputType === 'number' && e.target.value !== ''
              ? Number(e.target.value)
              : e.target.value,
        })
      }
    />
  );
}
