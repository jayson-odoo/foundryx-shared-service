'use client';

import { useRef, useState } from 'react';
import { Plus, Trash2, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { MultiSelect } from '@/components/platform/multi-select';
import type {
  FilterFieldDef,
  FilterFieldType,
  FilterGroup,
  FilterOperator,
  FilterRule,
} from '@/types/resource';

// Operators offered per field type, with labels.
const OPERATORS: Record<FilterFieldType, { value: FilterOperator; label: string }[]> = {
  text: [
    { value: 'contains', label: 'contains' },
    { value: 'eq', label: 'is' },
    { value: 'neq', label: 'is not' },
  ],
  enum: [
    { value: 'in', label: 'is any of' },
    { value: 'eq', label: 'is' },
  ],
  date: [
    { value: 'between', label: 'between' },
    { value: 'before', label: 'before' },
    { value: 'after', label: 'after' },
  ],
  bool: [
    { value: 'is_true', label: 'is yes' },
    { value: 'is_false', label: 'is no' },
  ],
};

// ---- Internal draft tree (carries a stable React key per node) ----
interface DraftCondition {
  key: string;
  kind: 'condition';
  field: string;
  operator: FilterOperator;
  value: unknown;
}
interface DraftGroup {
  key: string;
  kind: 'group';
  combinator: 'and' | 'or';
  rules: DraftRule[];
}
type DraftRule = DraftCondition | DraftGroup;

function toFilterRule(rule: DraftRule): FilterRule {
  if (rule.kind === 'group') {
    return { kind: 'group', combinator: rule.combinator, rules: rule.rules.map(toFilterRule) };
  }
  return {
    kind: 'condition',
    field: rule.field,
    operator: rule.operator,
    value: rule.value as FilterRule extends { value: infer V } ? V : never,
  } as FilterRule;
}

function isEmpty(group: DraftGroup): boolean {
  return group.rules.length === 0;
}

export interface FilterBuilderProps {
  fields: FilterFieldDef[];
  /** Called with the built group (or null to clear) when the user applies. */
  onApply: (group: FilterGroup | null) => void;
  onClose?: () => void;
}

export function FilterBuilder({ fields, onApply, onClose }: FilterBuilderProps) {
  const keyRef = useRef(0);
  const nextKey = () => `k${++keyRef.current}`;

  const newCondition = (): DraftCondition => ({
    key: nextKey(),
    kind: 'condition',
    field: fields[0]?.field ?? '',
    operator: OPERATORS[fields[0]?.type ?? 'text'][0].value,
    value: '',
  });

  const [root, setRoot] = useState<DraftGroup>(() => ({
    key: nextKey(),
    kind: 'group',
    combinator: 'and',
    rules: [newCondition()],
  }));

  const fieldDef = (name: string) => fields.find((f) => f.field === name);

  function apply() {
    onApply(isEmpty(root) ? null : (toFilterRule(root) as FilterGroup));
    onClose?.();
  }

  function clearAll() {
    setRoot({ key: nextKey(), kind: 'group', combinator: 'and', rules: [] });
    onApply(null);
  }

  return (
    <div className="flex flex-col gap-3 w-[min(92vw,32rem)]">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Filters</span>
        {onClose && (
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close filters">
            <X />
          </Button>
        )}
      </div>

      <GroupEditor
        group={root}
        depth={0}
        fields={fields}
        fieldDef={fieldDef}
        newCondition={newCondition}
        newGroup={() => ({ key: nextKey(), kind: 'group', combinator: 'and', rules: [newCondition()] })}
        onChange={setRoot}
      />

      <div className="flex items-center justify-end gap-2 pt-1">
        <Button variant="outline" size="sm" onClick={clearAll}>
          Clear
        </Button>
        <Button variant="primary" size="sm" onClick={apply}>
          Apply
        </Button>
      </div>
    </div>
  );
}

interface GroupEditorProps {
  group: DraftGroup;
  depth: number;
  fields: FilterFieldDef[];
  fieldDef: (name: string) => FilterFieldDef | undefined;
  newCondition: () => DraftCondition;
  newGroup: () => DraftGroup;
  onChange: (group: DraftGroup) => void;
}

function GroupEditor({
  group,
  depth,
  fields,
  fieldDef,
  newCondition,
  newGroup,
  onChange,
}: GroupEditorProps) {
  function updateRule(key: string, next: DraftRule | null) {
    onChange({
      ...group,
      rules: group.rules.flatMap((r) => (r.key === key ? (next ? [next] : []) : [r])),
    });
  }

  return (
    <div
      className={cn(
        'flex flex-col gap-2 rounded-lg border border-border p-3',
        depth > 0 && 'bg-muted/40',
      )}
    >
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">Match</span>
        <ToggleGroup
          type="single"
          size="sm"
          value={group.combinator}
          onValueChange={(v) => v && onChange({ ...group, combinator: v as 'and' | 'or' })}
        >
          <ToggleGroupItem value="and">AND</ToggleGroupItem>
          <ToggleGroupItem value="or">OR</ToggleGroupItem>
        </ToggleGroup>
      </div>

      <div className="flex flex-col gap-2">
        {group.rules.map((rule) =>
          rule.kind === 'condition' ? (
            <ConditionRow
              key={rule.key}
              condition={rule}
              fields={fields}
              fieldDef={fieldDef}
              onChange={(next) => updateRule(rule.key, next)}
              onRemove={() => updateRule(rule.key, null)}
            />
          ) : (
            <GroupEditor
              key={rule.key}
              group={rule}
              depth={depth + 1}
              fields={fields}
              fieldDef={fieldDef}
              newCondition={newCondition}
              newGroup={newGroup}
              onChange={(next) => updateRule(rule.key, next)}
            />
          ),
        )}
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onChange({ ...group, rules: [...group.rules, newCondition()] })}
        >
          <Plus /> Condition
        </Button>
        {depth < 2 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onChange({ ...group, rules: [...group.rules, newGroup()] })}
          >
            <Plus /> Group
          </Button>
        )}
      </div>
    </div>
  );
}

interface ConditionRowProps {
  condition: DraftCondition;
  fields: FilterFieldDef[];
  fieldDef: (name: string) => FilterFieldDef | undefined;
  onChange: (next: DraftCondition) => void;
  onRemove: () => void;
}

function ConditionRow({ condition, fields, fieldDef, onChange, onRemove }: ConditionRowProps) {
  const def = fieldDef(condition.field);
  const type: FilterFieldType = def?.type ?? 'text';
  const ops = OPERATORS[type];

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        value={condition.field}
        onValueChange={(field) => {
          const t = fieldDef(field)?.type ?? 'text';
          onChange({ ...condition, field, operator: OPERATORS[t][0].value, value: '' });
        }}
      >
        <SelectTrigger size="sm" className="w-32">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {fields.map((f) => (
            <SelectItem key={f.field} value={f.field}>
              {f.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={condition.operator}
        onValueChange={(operator) => onChange({ ...condition, operator: operator as FilterOperator })}
      >
        <SelectTrigger size="sm" className="w-28">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {ops.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <ConditionValue condition={condition} def={def} onChange={onChange} />

      <Button variant="ghost" size="sm" onClick={onRemove} aria-label="Remove condition">
        <Trash2 />
      </Button>
    </div>
  );
}

function ConditionValue({
  condition,
  def,
  onChange,
}: {
  condition: DraftCondition;
  def: FilterFieldDef | undefined;
  onChange: (next: DraftCondition) => void;
}) {
  const type = def?.type ?? 'text';

  if (type === 'bool') return null;

  if (type === 'enum') {
    if (condition.operator === 'in') {
      const selected = Array.isArray(condition.value) ? (condition.value as string[]) : [];
      return (
        <div className="min-w-48 flex-1">
          <MultiSelect
            options={def?.options ?? []}
            value={selected}
            onChange={(value) => onChange({ ...condition, value })}
            size="sm"
            placeholder="Select…"
          />
        </div>
      );
    }
    return (
      <Select
        value={typeof condition.value === 'string' ? condition.value : ''}
        onValueChange={(value) => onChange({ ...condition, value })}
      >
        <SelectTrigger size="sm" className="w-36">
          <SelectValue placeholder="Select…" />
        </SelectTrigger>
        <SelectContent>
          {(def?.options ?? []).map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  if (type === 'date') {
    if (condition.operator === 'between') {
      const v = Array.isArray(condition.value) ? (condition.value as string[]) : ['', ''];
      return (
        <div className="flex items-center gap-1">
          <Input
            type="date"
            className="h-8 w-36"
            value={v[0] ?? ''}
            onChange={(e) => onChange({ ...condition, value: [e.target.value, v[1] ?? ''] })}
          />
          <span className="text-xs text-muted-foreground">to</span>
          <Input
            type="date"
            className="h-8 w-36"
            value={v[1] ?? ''}
            onChange={(e) => onChange({ ...condition, value: [v[0] ?? '', e.target.value] })}
          />
        </div>
      );
    }
    return (
      <Input
        type="date"
        className="h-8 w-36"
        value={typeof condition.value === 'string' ? condition.value : ''}
        onChange={(e) => onChange({ ...condition, value: e.target.value })}
      />
    );
  }

  // text
  return (
    <Input
      className="h-8 w-40"
      placeholder="Value"
      value={typeof condition.value === 'string' ? condition.value : ''}
      onChange={(e) => onChange({ ...condition, value: e.target.value })}
    />
  );
}
