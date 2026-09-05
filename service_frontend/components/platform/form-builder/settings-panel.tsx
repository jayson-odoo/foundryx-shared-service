'use client';

/**
 * Form-builder settings panel (plan sprint-3/01 D7) - contextual on selection:
 * nothing → status line; page → title; section → title/description/two-column/
 * conditions; field → label/key/required/placeholder/help + per-type config +
 * a quick type-switch + visibility conditions. Every dropdown is a
 * SearchSelect/MultiSelect (house mandate); conditions use the shared
 * RuleBuilder (remounted via key on selection change). No instructional copy -
 * labels + a duplicate-key warning (state, not instruction) only.
 */
import { useMemo, useState } from 'react';
import { Calculator, GripVertical } from 'lucide-react';
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { Button } from '@/components/ui/button';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { cn } from '@/lib/utils';
import { FormulaBuilder } from './formula-builder';
import {
  CHOICE_FIELD_TYPES,
  NUMERIC_FIELD_TYPES,
  allFields,
  answerFacts,
  inputFields,
  newId,
} from '@/lib/form-doc';
import { ComputedExpressionError, fieldRefs, parseExpression } from '@/lib/computed-expr';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { MultiSelect } from '@/components/platform/multi-select';
import { RuleBuilder } from '@/components/platform/rule-builder';
import { SearchSelect, type SearchSelectGroup } from '@/components/platform/search-select';
import type { RuleGroup } from '@/types/rules';
import type {
  FormChoiceItem,
  FormDocument,
  FormField,
  FormFieldType,
  FormSection,
  FormSubField,
  FormSubFieldType,
  FormSummarize,
  FormTableColumn,
  FormTableConfig,
} from '@/types/forms';
import { COMMON_MIMES, PALETTE_CATEGORIES, SUB_FIELD_TYPES, fieldMeta } from './field-catalog';
import { OptionsEditor } from './options-editor';
import { TEXT_FAMILY } from './doc-ops';
import type { BuilderSelection } from './selection';

const KEY_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** A labelled settings row. */
function Row({ label, htmlFor, children }: { label: string; htmlFor?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <Label htmlFor={htmlFor} className="text-xs font-medium text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  );
}

function NumberInput({
  value,
  onChange,
  ariaLabel,
  testId,
}: {
  value: number | undefined;
  onChange: (n: number | undefined) => void;
  ariaLabel: string;
  testId?: string;
}) {
  return (
    <Input
      type="number"
      className="h-8 text-xs"
      aria-label={ariaLabel}
      data-testid={testId}
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
    />
  );
}

// ---- field-type SearchSelect options (compatible groups + all) ----

function typeSwitchGroups(): SearchSelectGroup[] {
  return PALETTE_CATEGORIES.map((category) => ({
    label: category.label,
    options: category.types.map((type) => ({
      value: type,
      label: fieldMeta(type).label,
    })),
  }));
}

// ---- type-specific config ----

export interface FieldConfigProps {
  doc: FormDocument;
  field: FormField;
  onPatch: (patch: Partial<FormField>) => void;
  onAddOption: () => void;
  onUpdateOption: (index: number, patch: Partial<FormChoiceItem>) => void;
  onRemoveOption: (index: number) => void;
  onMoveOption: (index: number, direction: -1 | 1) => void;
  onAddSubField: (type: FormSubFieldType) => void;
  onUpdateSubField: (subId: string, patch: Partial<FormSubField>) => void;
  onRemoveSubField: (subId: string) => void;
  onMoveSubField: (subId: string, direction: -1 | 1) => void;
}

function TypeConfig(props: FieldConfigProps) {
  const { field } = props;
  const type = field.type;

  if (TEXT_FAMILY.has(type)) {
    return (
      <div className="flex flex-col gap-2">
        <div className="grid grid-cols-2 gap-2">
          <Row label="Min length">
            <NumberInput
              ariaLabel="Min length"
              value={field.text?.minLength}
              onChange={(n) => props.onPatch({ text: { ...field.text, minLength: n } })}
            />
          </Row>
          <Row label="Max length">
            <NumberInput
              ariaLabel="Max length"
              value={field.text?.maxLength}
              onChange={(n) => props.onPatch({ text: { ...field.text, maxLength: n } })}
            />
          </Row>
        </div>
        <Row label="Pattern">
          <Input
            className="h-8 font-mono text-xs"
            aria-label="Pattern"
            value={field.text?.pattern ?? ''}
            onChange={(e) =>
              props.onPatch({ text: { ...field.text, pattern: e.target.value || undefined } })
            }
          />
        </Row>
        {field.text?.pattern && (
          <Row label="Pattern message">
            <Input
              className="h-8 text-xs"
              aria-label="Pattern message"
              value={field.text?.patternMessage ?? ''}
              onChange={(e) =>
                props.onPatch({ text: { ...field.text, patternMessage: e.target.value } })
              }
            />
          </Row>
        )}
      </div>
    );
  }

  if (type === 'number' || type === 'integer') {
    const isInteger = type === 'integer' || Boolean(field.number?.integer);
    return (
      <div className="grid grid-cols-2 gap-2">
        <Row label="Min">
          <NumberInput
            ariaLabel="Min"
            value={field.number?.min}
            onChange={(n) => props.onPatch({ number: { ...field.number, min: n } })}
          />
        </Row>
        <Row label="Max">
          <NumberInput
            ariaLabel="Max"
            value={field.number?.max}
            onChange={(n) => props.onPatch({ number: { ...field.number, max: n } })}
          />
        </Row>
        <Row label="Step">
          <NumberInput
            ariaLabel="Step"
            value={field.number?.step}
            onChange={(n) => props.onPatch({ number: { ...field.number, step: n } })}
          />
        </Row>
        {!isInteger && (
          <Row label="Decimal places">
            <NumberInput
              ariaLabel="Decimal places"
              value={field.number?.decimals}
              onChange={(n) => props.onPatch({ number: { ...field.number, decimals: n } })}
            />
          </Row>
        )}
      </div>
    );
  }

  if (CHOICE_FIELD_TYPES.has(type)) {
    return (
      <Row label="Options">
        <OptionsEditor
          items={field.options?.items ?? []}
          onAdd={props.onAddOption}
          onUpdate={props.onUpdateOption}
          onRemove={props.onRemoveOption}
          onMove={props.onMoveOption}
        />
      </Row>
    );
  }

  if (type === 'rating') {
    return (
      <Row label="Scale (max)">
        <NumberInput
          ariaLabel="Rating max"
          testId="rating-max"
          value={field.rating?.max}
          onChange={(n) => props.onPatch({ rating: { max: Math.max(1, Math.min(n ?? 5, 10)) } })}
        />
      </Row>
    );
  }

  if (type === 'file') {
    return (
      <div className="flex flex-col gap-2">
        <div className="grid grid-cols-2 gap-2">
          <Row label="Max size (MB)">
            <NumberInput
              ariaLabel="Max size MB"
              value={field.file?.maxSizeMb}
              onChange={(n) => props.onPatch({ file: { ...field.file, maxSizeMb: n } })}
            />
          </Row>
          <Row label="Max files">
            <NumberInput
              ariaLabel="Max files"
              value={field.file?.maxCount}
              onChange={(n) => props.onPatch({ file: { ...field.file, maxCount: n } })}
            />
          </Row>
        </div>
        <Row label="Allowed file types">
          <MultiSelect
            options={COMMON_MIMES}
            value={field.file?.allowedMimes ?? []}
            onChange={(mimes) => props.onPatch({ file: { ...field.file, allowedMimes: mimes } })}
            placeholder="Any type"
          />
        </Row>
      </div>
    );
  }

  if (type === 'heading') {
    return (
      <Row label="Level">
        <SearchSelect
          ariaLabel="Heading level"
          options={[
            { value: '1', label: 'H1' },
            { value: '2', label: 'H2' },
            { value: '3', label: 'H3' },
          ]}
          value={String(field.heading?.level ?? 2)}
          onChange={(v) => props.onPatch({ heading: { level: Number(v) as 1 | 2 | 3 } })}
        />
      </Row>
    );
  }

  if (type === 'repeater') {
    return <RepeaterConfig {...props} />;
  }

  if (type === 'table') {
    return <TableConfig {...props} />;
  }

  if (type === 'computed') {
    return <ComputedConfig {...props} />;
  }

  return null;
}

// ---- repeater sub-field editor ----

/** Sortable wrapper (render-prop) - provides the drag handle so a row's
 * existing JSX can keep its layout (table columns + repeater sub-fields). */
function SortableShell({ id, children }: { id: string; children: (handle: React.ReactNode) => React.ReactNode }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  const handle = (
    <button
      type="button"
      aria-label="Drag to reorder"
      className="cursor-grab px-0.5 text-muted-foreground/60 hover:text-foreground"
      {...listeners}
      {...attributes}
    >
      <GripVertical className="size-4" />
    </button>
  );
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn(isDragging && 'opacity-50')}
    >
      {children(handle)}
    </div>
  );
}

function RepeaterConfig(props: FieldConfigProps) {
  const { field } = props;
  const subs = field.repeater?.fields ?? [];
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));
  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return;
    const from = subs.findIndex((s) => s.id === e.active.id);
    const to = subs.findIndex((s) => s.id === e.over!.id);
    if (from < 0 || to < 0) return;
    props.onPatch({ repeater: { ...field.repeater!, fields: arrayMove(subs, from, to) } });
  };
  return (
    <div className="flex flex-col gap-2">
      <Row label="Sub-fields">
        <div className="flex flex-col gap-2" data-testid="subfield-editor">
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={subs.map((s) => s.id)} strategy={verticalListSortingStrategy}>
          {subs.map((sub, index) => (
            <SortableShell key={sub.id} id={sub.id}>
              {(handle) => (
            <div className="rounded-md border border-input p-2">
              <div className="flex items-center gap-1">
                {handle}
                <SearchSelect
                  ariaLabel={`Sub-field ${index + 1} type`}
                  className="h-8 flex-1"
                  options={SUB_FIELD_TYPES.map((t) => ({ value: t, label: fieldMeta(t).label }))}
                  value={sub.type}
                  onChange={(v) => props.onUpdateSubField(sub.id, { type: v as FormSubFieldType })}
                />
                <button
                  type="button"
                  aria-label="Remove sub-field"
                  data-testid={`subfield-remove-${index}`}
                  className={cn(PRESSED_CLASS, 'px-1 text-xs text-destructive')}
                  onClick={() => props.onRemoveSubField(sub.id)}
                >
                  ✕
                </button>
              </div>
              <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                <Input
                  className="h-8 font-mono text-xs"
                  aria-label={`Sub-field ${index + 1} key`}
                  placeholder="key"
                  value={sub.key}
                  onChange={(e) => props.onUpdateSubField(sub.id, { key: e.target.value })}
                />
                <Input
                  className="h-8 text-xs"
                  aria-label={`Sub-field ${index + 1} label`}
                  placeholder="Label"
                  value={sub.label}
                  onChange={(e) => props.onUpdateSubField(sub.id, { label: e.target.value })}
                />
              </div>
              <div className="mt-1.5 flex items-center gap-2">
                <Switch
                  checked={Boolean(sub.required)}
                  onCheckedChange={(checked) => props.onUpdateSubField(sub.id, { required: checked })}
                  aria-label={`Sub-field ${index + 1} required`}
                />
                <span className="text-xs text-muted-foreground">Required</span>
              </div>
              {(sub.type === 'select' || sub.type === 'radio') && (
                <div className="mt-2">
                  <OptionsEditor
                    items={sub.options?.items ?? []}
                    onAdd={() =>
                      props.onUpdateSubField(sub.id, {
                        options: {
                          kind: 'static',
                          items: [
                            ...(sub.options?.items ?? []),
                            {
                              value: `option_${(sub.options?.items.length ?? 0) + 1}`,
                              label: `Option ${(sub.options?.items.length ?? 0) + 1}`,
                            },
                          ],
                        },
                      })
                    }
                    onUpdate={(i, patch) =>
                      props.onUpdateSubField(sub.id, {
                        options: {
                          kind: 'static',
                          items: (sub.options?.items ?? []).map((it, ii) =>
                            ii === i ? { ...it, ...patch } : it,
                          ),
                        },
                      })
                    }
                    onRemove={(i) =>
                      props.onUpdateSubField(sub.id, {
                        options: {
                          kind: 'static',
                          items: (sub.options?.items ?? []).filter((_, ii) => ii !== i),
                        },
                      })
                    }
                    onMove={(i, dir) => {
                      const items = [...(sub.options?.items ?? [])];
                      const t = i + dir;
                      if (t < 0 || t >= items.length) return;
                      [items[i], items[t]] = [items[t], items[i]];
                      props.onUpdateSubField(sub.id, { options: { kind: 'static', items } });
                    }}
                  />
                </div>
              )}
              {sub.type === 'rating' && (
                <div className="mt-2">
                  <Row label="Scale (max)">
                    <NumberInput
                      ariaLabel="Sub-field rating max"
                      value={sub.rating?.max}
                      onChange={(n) =>
                        props.onUpdateSubField(sub.id, {
                          rating: { max: Math.max(1, Math.min(n ?? 5, 10)) },
                        })
                      }
                    />
                  </Row>
                </div>
              )}
            </div>
              )}
            </SortableShell>
          ))}
            </SortableContext>
          </DndContext>
          <SearchSelect
            ariaLabel="Add sub-field type"
            placeholder="Add sub-field…"
            options={SUB_FIELD_TYPES.map((t) => ({ value: t, label: fieldMeta(t).label }))}
            value={null}
            onChange={(v) => props.onAddSubField(v as FormSubFieldType)}
          />
        </div>
      </Row>
      <div className="grid grid-cols-2 gap-2">
        <Row label="Min rows">
          <NumberInput
            ariaLabel="Min rows"
            value={field.repeater?.minRows}
            onChange={(n) =>
              props.onPatch({ repeater: { ...field.repeater!, minRows: n } })
            }
          />
        </Row>
        <Row label="Max rows">
          <NumberInput
            ariaLabel="Max rows"
            value={field.repeater?.maxRows}
            onChange={(n) =>
              props.onPatch({ repeater: { ...field.repeater!, maxRows: n } })
            }
          />
        </Row>
      </div>
    </div>
  );
}

// ---- table column editor (sprint-3/02) ----

const TABLE_COLUMN_TYPE_OPTIONS: { value: FormTableColumn['type']; label: string }[] = [
  { value: 'text', label: 'Text' },
  { value: 'number', label: 'Number (decimal)' },
  { value: 'integer', label: 'Integer' },
  { value: 'select', label: 'Select' },
  { value: 'date', label: 'Date' },
  { value: 'computed', label: 'Computed' },
  { value: 'fixed', label: 'Fixed value' },
];

const SUMMARIZE_OPTIONS = [
  { value: 'none', label: 'No total' },
  { value: 'sum', label: 'Sum' },
  { value: 'avg', label: 'Average' },
  { value: 'count', label: 'Count' },
  { value: 'min', label: 'Min' },
  { value: 'max', label: 'Max' },
];

function TableConfig({ field, onPatch }: FieldConfigProps) {
  const table: FormTableConfig = field.table ?? { columns: [] };
  const columns = table.columns;
  const patchTable = (patch: Partial<FormTableConfig>) => onPatch({ table: { ...table, ...patch } });
  const updateCol = (id: string, patch: Partial<FormTableColumn>) =>
    patchTable({ columns: columns.map((c) => (c.id === id ? { ...c, ...patch } : c)) });
  const removeCol = (id: string) => patchTable({ columns: columns.filter((c) => c.id !== id) });
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));
  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return;
    const from = columns.findIndex((c) => c.id === e.active.id);
    const to = columns.findIndex((c) => c.id === e.over!.id);
    if (from < 0 || to < 0) return;
    patchTable({ columns: arrayMove(columns, from, to) });
  };
  const addCol = () => {
    // Unique key vs the existing set - `length + 1` collides after a middle
    // column was removed (publish-gate dup-key reject; code-review).
    const used = new Set(columns.map((c) => c.key));
    let n = columns.length + 1;
    while (used.has(`col_${n}`)) n += 1;
    patchTable({
      columns: [...columns, { id: newId('col'), type: 'text', key: `col_${n}`, label: `Column ${n}` }],
    });
  };

  return (
    <div className="flex flex-col gap-3">
      <Row label="Columns">
        <div className="flex flex-col gap-2" data-testid="table-columns">
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={columns.map((c) => c.id)} strategy={verticalListSortingStrategy}>
              {columns.map((col, index) => (
                <TableColumnEditor
                  key={col.id}
                  col={col}
                  index={index}
                  earlierNumeric={columns.slice(0, index).filter((c) => ['number', 'integer', 'computed', 'fixed'].includes(c.type))}
                  onUpdate={(patch) => updateCol(col.id, patch)}
                  onRemove={() => removeCol(col.id)}
                />
              ))}
            </SortableContext>
          </DndContext>
          <button
            type="button"
            className={cn(PRESSED_CLASS, 'self-start text-xs font-medium text-primary')}
            data-testid="table-add-column"
            onClick={addCol}
          >
            + Add column
          </button>
        </div>
      </Row>
      <Row label="Row numbers">
        <div className="flex items-center gap-2">
          <Switch
            checked={Boolean(table.showRowNumbers)}
            onCheckedChange={(checked) => patchTable({ showRowNumbers: checked })}
            aria-label="Show row numbers"
          />
          <span className="text-xs text-muted-foreground">Show a numbered (#) column</span>
        </div>
      </Row>
    </div>
  );
}

interface TableColumnEditorProps {
  col: FormTableColumn;
  index: number;
  earlierNumeric: FormTableColumn[];
  onUpdate: (patch: Partial<FormTableColumn>) => void;
  onRemove: () => void;
}

function TableColumnEditor({ col, index, earlierNumeric, onUpdate, onRemove }: TableColumnEditorProps) {
  const [builderOpen, setBuilderOpen] = useState(false);
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: col.id });
  const sortableStyle = { transform: CSS.Translate.toString(transform), transition };
  const isNumeric = col.type === 'number' || col.type === 'integer' || col.type === 'computed';
  const numericKeys = useMemo(() => new Set(earlierNumeric.map((c) => c.key)), [earlierNumeric]);

  const validateColumnFormula = (expr: string): string | null => {
    const trimmed = expr.trim();
    if (!trimmed) return null;
    try {
      parseExpression(trimmed);
    } catch (error) {
      return error instanceof ComputedExpressionError ? error.message : 'Invalid expression.';
    }
    const bad = Array.from(fieldRefs(trimmed) ?? new Set<string>()).filter((r) => !numericKeys.has(r));
    return bad.length ? `Not an earlier numeric column: ${bad.join(', ')}` : null;
  };

  return (
    <div
      ref={setNodeRef}
      style={sortableStyle}
      className={cn('rounded-md border border-input p-2', isDragging && 'opacity-50')}
    >
      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-label={`Drag column ${index + 1}`}
          className={cn('cursor-grab px-0.5 text-muted-foreground/60 hover:text-foreground')}
          {...listeners}
          {...attributes}
        >
          <GripVertical className="size-4" />
        </button>
        <SearchSelect
          ariaLabel={`Column ${index + 1} type`}
          className="h-8 flex-1"
          options={TABLE_COLUMN_TYPE_OPTIONS}
          value={col.type}
          onChange={(v) => onUpdate({ type: v as FormTableColumn['type'] })}
        />
        <button
          type="button"
          aria-label="Remove column"
          className={cn(PRESSED_CLASS, 'px-1 text-xs text-destructive')}
          onClick={onRemove}
        >
          ✕
        </button>
      </div>
      <div className="mt-1.5 grid grid-cols-2 gap-1.5">
        <Input
          className="h-8 font-mono text-xs"
          aria-label={`Column ${index + 1} key`}
          placeholder="key"
          value={col.key}
          onChange={(e) => onUpdate({ key: e.target.value })}
        />
        <Input
          className="h-8 text-xs"
          aria-label={`Column ${index + 1} label`}
          placeholder="Label"
          value={col.label}
          onChange={(e) => onUpdate({ label: e.target.value })}
        />
      </div>

      {col.type !== 'computed' && col.type !== 'fixed' && (
        <div className="mt-1.5 flex items-center gap-2">
          <Switch
            checked={Boolean(col.required)}
            onCheckedChange={(checked) => onUpdate({ required: checked })}
            aria-label={`Column ${index + 1} required`}
          />
          <span className="text-xs text-muted-foreground">Required</span>
        </div>
      )}

      {col.type === 'fixed' && (
        <Input
          className="mt-1.5 h-8 text-xs"
          aria-label={`Column ${index + 1} fixed value`}
          placeholder="Fixed value (e.g. 0.06)"
          value={col.fixedValue ?? ''}
          onChange={(e) => onUpdate({ fixedValue: e.target.value })}
        />
      )}

      {col.type === 'computed' && (
        <div className="mt-1.5 flex items-center gap-1.5">
          <Input
            className="h-8 flex-1 font-mono text-xs"
            aria-label={`Column ${index + 1} expression`}
            placeholder="qty * unit_price"
            value={col.computed?.expression ?? ''}
            onChange={(e) => onUpdate({ computed: { expression: e.target.value } })}
          />
          <Button type="button" variant="outline" size="sm" className="h-8 shrink-0" onClick={() => setBuilderOpen(true)}>
            Build
          </Button>
          <FormulaBuilder
            open={builderOpen}
            onOpenChange={setBuilderOpen}
            value={col.computed?.expression ?? ''}
            onChange={(expr) => onUpdate({ computed: { expression: expr } })}
            variables={earlierNumeric.map((c) => ({ label: c.label || c.key, token: c.key }))}
            validate={validateColumnFormula}
            title="Build column formula"
          />
        </div>
      )}

      {col.type === 'select' && (
        <div className="mt-2">
          <OptionsEditor
            items={col.options?.items ?? []}
            onAdd={() =>
              onUpdate({
                options: {
                  kind: 'static',
                  items: [
                    ...(col.options?.items ?? []),
                    { value: `option_${(col.options?.items.length ?? 0) + 1}`, label: `Option ${(col.options?.items.length ?? 0) + 1}` },
                  ],
                },
              })
            }
            onUpdate={(i, patch) =>
              onUpdate({
                options: {
                  kind: 'static',
                  items: (col.options?.items ?? []).map((it, ii) => (ii === i ? { ...it, ...patch } : it)),
                },
              })
            }
            onRemove={(i) =>
              onUpdate({
                options: { kind: 'static', items: (col.options?.items ?? []).filter((_, ii) => ii !== i) },
              })
            }
            onMove={(i, dir) => {
              const items = [...(col.options?.items ?? [])];
              const target = i + dir;
              if (target < 0 || target >= items.length) return;
              [items[i], items[target]] = [items[target], items[i]];
              onUpdate({ options: { kind: 'static', items } });
            }}
          />
        </div>
      )}

      {(col.type === 'number' || col.type === 'computed' || col.type === 'fixed') && (
        <div className="mt-1.5 flex items-center gap-2">
          <span className="whitespace-nowrap text-xs text-muted-foreground">Decimal places</span>
          <Input
            type="number"
            className="h-8 w-20 text-xs"
            aria-label={`Column ${index + 1} decimals`}
            value={col.decimals ?? ''}
            onChange={(e) => onUpdate({ decimals: e.target.value === '' ? undefined : Number(e.target.value) })}
          />
        </div>
      )}

      {isNumeric && (
        <div className="mt-1.5 flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Column total</span>
          <SearchSelect
            ariaLabel={`Column ${index + 1} total`}
            className="h-8 flex-1"
            options={SUMMARIZE_OPTIONS}
            value={col.summarize ?? 'none'}
            onChange={(v) => onUpdate({ summarize: !v || v === 'none' ? undefined : (v as FormSummarize) })}
          />
        </div>
      )}
    </div>
  );
}

// ---- computed expression editor ----

interface ComputedVariable {
  label: string;
  token: string;
}

/** Every variable a computed field can reference, in document order: earlier
 * numeric scalar fields (insert the key) + earlier repeater columns as
 * aggregate functions (sum/avg/min/max over the column, count over rows). */
function computedVariables(doc: FormDocument, fieldId: string): ComputedVariable[] {
  const out: ComputedVariable[] = [];
  for (const { field: f } of allFields(doc)) {
    if (f.id === fieldId) break;
    if (!f.key) continue;
    if (NUMERIC_FIELD_TYPES.has(f.type)) {
      out.push({ label: f.label || f.key, token: f.key });
    }
    const container =
      f.type === 'repeater' && f.repeater
        ? { label: f.label || f.key, numeric: f.repeater.fields.filter((s) => s.key && NUMERIC_FIELD_TYPES.has(s.type)) }
        : f.type === 'table' && f.table
          ? {
              label: f.label || f.key,
              numeric: f.table.columns.filter(
                (c) => c.key && ['number', 'integer', 'computed', 'fixed'].includes(c.type),
              ),
            }
          : null;
    if (container) {
      for (const col of container.numeric) {
        const colLabel = col.label || col.key;
        for (const fn of ['sum', 'avg', 'min', 'max'] as const) {
          out.push({ label: `${fn} of ${colLabel}`, token: `${fn}(${f.key}.${col.key})` });
        }
      }
      out.push({ label: `count of ${container.label}`, token: `count(${f.key})` });
    }
  }
  return out;
}

function ComputedConfig({ doc, field, onPatch }: FieldConfigProps) {
  const expression = field.computed?.expression ?? '';
  const [builderOpen, setBuilderOpen] = useState(false);
  const variables = useMemo(() => computedVariables(doc, field.id), [doc, field.id]);

  const analysis = useMemo(() => {
    const trimmed = expression.trim();
    if (!trimmed) return { error: null as string | null, badRefs: [] as string[] };
    try {
      parseExpression(trimmed);
    } catch (error) {
      const message =
        error instanceof ComputedExpressionError ? error.message : 'Invalid expression.';
      return { error: message, badRefs: [] };
    }
    // Warn when a SCALAR ref isn't an EARLIER numeric field (aggregate refs are
    // validated against repeater columns by the publish gate, not flagged here).
    const refs = fieldRefs(trimmed) ?? new Set<string>();
    const earlierNumericKeys = new Set<string>();
    for (const { field: f } of allFields(doc)) {
      if (f.id === field.id) break;
      if (f.key && NUMERIC_FIELD_TYPES.has(f.type)) earlierNumericKeys.add(f.key);
    }
    const badRefs = Array.from(refs).filter((r) => !earlierNumericKeys.has(r));
    return { error: null, badRefs };
  }, [doc, expression, field.id]);

  const validateFormula = (expr: string): string | null => {
    const trimmed = expr.trim();
    if (!trimmed) return null;
    try {
      parseExpression(trimmed);
    } catch (error) {
      return error instanceof ComputedExpressionError ? error.message : 'Invalid expression.';
    }
    const earlierNumericKeys = new Set<string>();
    for (const { field: f } of allFields(doc)) {
      if (f.id === field.id) break;
      if (f.key && NUMERIC_FIELD_TYPES.has(f.type)) earlierNumericKeys.add(f.key);
    }
    const bad = Array.from(fieldRefs(trimmed) ?? new Set<string>()).filter((r) => !earlierNumericKeys.has(r));
    return bad.length ? `References not an earlier numeric field: ${bad.join(', ')}` : null;
  };

  return (
    <Row label="Expression">
      <div className="flex items-center gap-1.5">
        <div className="relative flex-1">
          <Calculator className="pointer-events-none absolute start-2.5 top-2.5 size-3.5 text-muted-foreground" />
          <Input
            className="h-9 ps-8 font-mono text-xs"
            aria-label="Expression"
            data-testid="computed-expression"
            placeholder="sum(lines.qty) * 1.1"
            value={expression}
            onChange={(e) => onPatch({ computed: { expression: e.target.value } })}
          />
        </div>
        <Button type="button" variant="outline" size="sm" className="h-9 shrink-0" onClick={() => setBuilderOpen(true)}>
          Build
        </Button>
      </div>

      <FormulaBuilder
        open={builderOpen}
        onOpenChange={setBuilderOpen}
        value={expression}
        onChange={(expr) => onPatch({ computed: { expression: expr } })}
        variables={variables}
        validate={validateFormula}
      />

      {analysis.error && (
        <p className="text-xs text-destructive" data-testid="computed-error">
          {analysis.error}
        </p>
      )}
      {!analysis.error && analysis.badRefs.length > 0 && (
        <p className="text-xs text-amber-600" data-testid="computed-warning">
          References not an earlier numeric field: {analysis.badRefs.join(', ')}
        </p>
      )}
    </Row>
  );
}

// ---- the panel ----

export interface SettingsPanelProps {
  doc: FormDocument;
  selection: BuilderSelection;
  onPagePatch: (pageId: string, patch: { title?: string }) => void;
  onSectionPatch: (sectionId: string, patch: Partial<FormSection>) => void;
  onFieldPatch: (fieldId: string, patch: Partial<FormField>) => void;
  onFieldTypeChange: (fieldId: string, type: FormFieldType) => void;
  config: Omit<FieldConfigProps, 'doc' | 'field' | 'onPatch'>;
}

export function SettingsPanel({
  doc,
  selection,
  onPagePatch,
  onSectionPatch,
  onFieldPatch,
  onFieldTypeChange,
  config,
}: SettingsPanelProps) {
  if (!selection) {
    return (
      <p className="px-1 py-8 text-center text-xs text-muted-foreground" data-testid="settings-empty">
        Select a field to configure
      </p>
    );
  }

  if (selection.kind === 'page') {
    const page = doc.pages.find((p) => p.id === selection.id);
    if (!page) return null;
    return (
      <div className="flex flex-col gap-3" data-testid="settings-page">
        <Row label="Page title">
          <Input
            className="h-8 text-xs"
            aria-label="Page title field"
            value={page.title ?? ''}
            onChange={(e) => onPagePatch(page.id, { title: e.target.value })}
          />
        </Row>
      </div>
    );
  }

  if (selection.kind === 'section') {
    const section = doc.pages.flatMap((p) => p.sections).find((s) => s.id === selection.id);
    if (!section) return null;
    const facts = answerFacts(doc, { sectionId: section.id });
    return (
      <div className="flex flex-col gap-3" data-testid="settings-section">
        <Row label="Section title">
          <Input
            className="h-8 text-xs"
            aria-label="Section title field"
            value={section.title ?? ''}
            onChange={(e) => onSectionPatch(section.id, { title: e.target.value })}
          />
        </Row>
        <Row label="Description">
          <Textarea
            className="min-h-16 text-xs"
            aria-label="Section description"
            value={section.description ?? ''}
            onChange={(e) => onSectionPatch(section.id, { description: e.target.value })}
          />
        </Row>
        <div className="flex items-center gap-2">
          <Switch
            checked={Boolean(section.twoColumn)}
            onCheckedChange={(checked) => onSectionPatch(section.id, { twoColumn: checked })}
            aria-label="Two-column layout"
          />
          <span className="text-xs text-muted-foreground">Two-column layout</span>
        </div>
        <Row label="Visible when">
          <RuleBuilder
            key={`sec-${section.id}`}
            facts={facts}
            value={section.conditionsJson ?? null}
            onChange={(group: RuleGroup | null) =>
              onSectionPatch(section.id, { conditionsJson: group })
            }
          />
        </Row>
      </div>
    );
  }

  // field
  const located = doc.pages
    .flatMap((p) => p.sections)
    .flatMap((s) => s.fields)
    .find((f) => f.id === selection.id);
  if (!located) return null;
  const field = located;
  const isDisplay = field.type === 'heading' || field.type === 'paragraph' || field.type === 'divider';

  // Duplicate-key detection (warning, not instruction).
  const keyDuplicate =
    field.key &&
    inputFields(doc).some((f) => f.id !== field.id && f.key === field.key);
  const keyMalformed = field.key != null && field.key !== '' && !KEY_PATTERN.test(field.key);

  const facts = answerFacts(doc, { fieldId: field.id });

  return (
    <div className="flex flex-col gap-3" data-testid="settings-field">
      <Row label="Field type">
        <SearchSelect
          ariaLabel="Field type"
          groups={typeSwitchGroups()}
          value={field.type}
          onChange={(v) => onFieldTypeChange(field.id, v as FormFieldType)}
        />
      </Row>

      <Row label="Label">
        <Input
          className="h-8 text-xs"
          aria-label="Field label"
          data-testid="field-label"
          value={field.label}
          onChange={(e) => onFieldPatch(field.id, { label: e.target.value })}
        />
      </Row>

      {!isDisplay && (
        <>
          <Row label="Answer key">
            <Input
              className="h-8 font-mono text-xs"
              aria-label="Answer key"
              data-testid="field-key"
              value={field.key ?? ''}
              onChange={(e) => onFieldPatch(field.id, { key: e.target.value })}
            />
            {keyMalformed && (
              <p className="text-xs text-destructive" data-testid="key-malformed">
                Use letters, digits and underscores; start with a letter or underscore.
              </p>
            )}
            {keyDuplicate && !keyMalformed && (
              <p className="text-xs text-destructive" data-testid="key-duplicate">
                Another field already uses this key.
              </p>
            )}
          </Row>

          <div className="flex items-center gap-2">
            <Switch
              checked={Boolean(field.required)}
              onCheckedChange={(checked) => onFieldPatch(field.id, { required: checked })}
              aria-label="Required"
              data-testid="field-required"
            />
            <span className="text-xs text-muted-foreground">Required</span>
          </div>

          <Row label="Placeholder">
            <Input
              className="h-8 text-xs"
              aria-label="Placeholder"
              value={field.placeholder ?? ''}
              onChange={(e) => onFieldPatch(field.id, { placeholder: e.target.value })}
            />
          </Row>

          <Row label="Help text">
            <Input
              className="h-8 text-xs"
              aria-label="Help text"
              value={field.helpText ?? ''}
              onChange={(e) => onFieldPatch(field.id, { helpText: e.target.value })}
            />
          </Row>
        </>
      )}

      <TypeConfig doc={doc} field={field} onPatch={(patch) => onFieldPatch(field.id, patch)} {...config} />

      {!isDisplay && (
        <Row label="Visible when">
          <RuleBuilder
            key={`fld-${field.id}`}
            facts={facts}
            value={field.conditionsJson ?? null}
            onChange={(group: RuleGroup | null) => onFieldPatch(field.id, { conditionsJson: group })}
          />
        </Row>
      )}
    </div>
  );
}
