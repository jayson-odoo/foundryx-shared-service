/**
 * Pure helpers over the form block document (plan sprint-3/01 D6) - the
 * editor-agnostic Page → Section → Field contract. All functions are
 * immutable so the builder's undo/redo keeps snapshot history (workflow-doc
 * precedent). `validateFormDoc` is the CLIENT mirror of the backend publish
 * gate (`validate_form_doc`) - keep PARITY, including empty-array = missing.
 */
import { aggregateRefs, fieldRefs, parseExpression } from '@/lib/computed-expr';
import { evaluateRules } from '@/lib/rule-eval';
import type { RuleFact, RuleGroup } from '@/types/rules';
import type {
  FormAnswers,
  FormDocument,
  FormField,
  FormFieldType,
  FormInputFieldType,
  FormPage,
  FormSection,
  FormSubField,
  FormSubFieldType,
} from '@/types/forms';
import { FORM_SCHEMA_VERSION } from '@/types/forms';

/** Stable short id (forever-contract ids - workflow `newId` precedent). */
export function newId(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 8)}`;
}

// ---- field taxonomy metadata ----

export const DISPLAY_FIELD_TYPES: ReadonlySet<FormFieldType> = new Set<FormFieldType>([
  'heading',
  'paragraph',
  'divider',
]);

export const CHOICE_FIELD_TYPES: ReadonlySet<FormFieldType> = new Set<FormFieldType>([
  'select',
  'multiselect',
  'radio',
  'checkboxes',
]);

/** Field types whose answers can feed a computed expression. */
export const NUMERIC_FIELD_TYPES: ReadonlySet<FormFieldType> = new Set<FormFieldType>([
  'number',
  'integer',
  'rating',
  'computed',
]);

/** Field types usable as rule-engine condition facts (composites/uploads
 * excluded v1). */
const CONDITIONABLE_TYPES: ReadonlySet<FormFieldType> = new Set<FormFieldType>([
  'text',
  'textarea',
  'email',
  'phone',
  'url',
  'number',
  'integer',
  'select',
  'multiselect',
  'radio',
  'checkboxes',
  'yesno',
  'date',
  'datetime',
  'rating',
  'computed',
]);

export function isDisplayField(field: FormField): boolean {
  return DISPLAY_FIELD_TYPES.has(field.type);
}

export function isInputField(field: FormField): boolean {
  return !DISPLAY_FIELD_TYPES.has(field.type);
}

// ---- constructors ----

export function emptyFormDoc(): FormDocument {
  return {
    schemaVersion: FORM_SCHEMA_VERSION,
    pages: [createPage()],
  };
}

export function createPage(): FormPage {
  return { id: newId('pg'), title: '', sections: [createSection()] };
}

export function createSection(): FormSection {
  return { id: newId('sec'), title: '', fields: [] };
}

let keyCounter = 0;

/** A unique, human-readable answer key for a new field of `type`. */
export function suggestKey(doc: FormDocument, type: FormInputFieldType): string {
  const taken = new Set(allFields(doc).map((f) => f.field.key).filter(Boolean));
  const base = type;
  for (let i = 1; i < 1000; i += 1) {
    const candidate = i === 1 ? base : `${base}${i}`;
    if (!taken.has(candidate)) return candidate;
  }
  keyCounter += 1;
  return `${base}_${keyCounter}`;
}

const FIELD_DEFAULT_LABELS: Record<FormFieldType, string> = {
  text: 'Text',
  textarea: 'Long text',
  email: 'Email',
  phone: 'Phone',
  url: 'Website',
  number: 'Number (decimal)',
  integer: 'Integer',
  select: 'Dropdown',
  multiselect: 'Multi select',
  radio: 'Single choice',
  checkboxes: 'Checkboxes',
  yesno: 'Yes / No',
  date: 'Date',
  datetime: 'Date & time',
  file: 'File upload',
  signature: 'Signature',
  rating: 'Rating',
  address: 'Address',
  repeater: 'Repeating items',
  table: 'Table',
  computed: 'Calculated value',
  heading: 'Heading',
  paragraph: 'Paragraph',
  divider: 'Divider',
};

export function fieldDefaultLabel(type: FormFieldType): string {
  return FIELD_DEFAULT_LABELS[type] ?? type;
}

/** A freshly-added field of `type` with sensible defaults. */
export function createField(doc: FormDocument, type: FormFieldType): FormField {
  const field: FormField = {
    id: newId('fld'),
    type,
    label: fieldDefaultLabel(type),
  };
  if (!DISPLAY_FIELD_TYPES.has(type)) {
    field.key = suggestKey(doc, type as FormInputFieldType);
  }
  if (CHOICE_FIELD_TYPES.has(type)) {
    field.options = {
      kind: 'static',
      items: [
        { value: 'option_1', label: 'Option 1' },
        { value: 'option_2', label: 'Option 2' },
      ],
    };
  }
  if (type === 'rating') field.rating = { max: 5 };
  if (type === 'heading') field.heading = { level: 2 };
  if (type === 'repeater') {
    field.repeater = {
      fields: [
        { id: newId('sub'), type: 'text', key: 'item', label: 'Item' },
      ],
    };
  }
  if (type === 'table') {
    // A PO/SO-style starter: Item · Qty · Unit Price · Amount(computed).
    field.table = {
      showRowNumbers: true,
      columns: [
        { id: newId('col'), type: 'text', key: 'item', label: 'Item', required: true },
        { id: newId('col'), type: 'number', key: 'qty', label: 'Qty', required: true },
        { id: newId('col'), type: 'number', key: 'unit_price', label: 'Unit Price' },
        {
          id: newId('col'),
          type: 'computed',
          key: 'amount',
          label: 'Amount',
          computed: { expression: 'qty * unit_price' },
          summarize: 'sum',
        },
      ],
    };
  }
  if (type === 'computed') field.computed = { expression: '' };
  return field;
}

export function createSubField(repeater: FormSubField[], type: FormSubFieldType): FormSubField {
  const taken = new Set(repeater.map((f) => f.key));
  let key: string = type;
  for (let i = 2; taken.has(key); i += 1) key = `${type}${i}`;
  const sub: FormSubField = { id: newId('sub'), type, key, label: fieldDefaultLabel(type) };
  if (type === 'select' || type === 'radio') {
    sub.options = {
      kind: 'static',
      items: [
        { value: 'option_1', label: 'Option 1' },
        { value: 'option_2', label: 'Option 2' },
      ],
    };
  }
  if (type === 'rating') sub.rating = { max: 5 };
  return sub;
}

// ---- traversal ----

export interface FieldLocation {
  field: FormField;
  pageIndex: number;
  sectionIndex: number;
  fieldIndex: number;
}

/** Every field in DOCUMENT ORDER (conditions may only look backwards, D14). */
export function allFields(doc: FormDocument): FieldLocation[] {
  const out: FieldLocation[] = [];
  doc.pages.forEach((page, pageIndex) => {
    page.sections.forEach((section, sectionIndex) => {
      section.fields.forEach((field, fieldIndex) => {
        out.push({ field, pageIndex, sectionIndex, fieldIndex });
      });
    });
  });
  return out;
}

export function inputFields(doc: FormDocument): FormField[] {
  return allFields(doc)
    .map((loc) => loc.field)
    .filter(isInputField);
}

/** First input field with the given answer key (live per-field validation). */
export function fieldByKey(doc: FormDocument, key: string): FormField | undefined {
  return inputFields(doc).find((f) => f.key === key);
}

export function findField(doc: FormDocument, fieldId: string): FieldLocation | null {
  return allFields(doc).find((loc) => loc.field.id === fieldId) ?? null;
}

// ---- rule facts (conditional visibility authoring) ----

const FACT_SOURCE = 'answers';
const FACT_SOURCE_LABEL = 'Answers';

function factType(field: FormField): RuleFact['type'] {
  if (NUMERIC_FIELD_TYPES.has(field.type)) return 'number';
  if (field.type === 'yesno') return 'boolean';
  if (field.type === 'date' || field.type === 'datetime') return 'date';
  if (field.type === 'select' || field.type === 'radio') return 'enum';
  if (field.type === 'multiselect' || field.type === 'checkboxes') return 'list';
  return 'string';
}

/**
 * The rule facts available to a field's / section's visibility conditions -
 * answer facts of fields EARLIER in document order (bans cycles AND forward
 * refs; the backend publish gate enforces the same).
 *
 * `before`: the field id (or section id) authoring the condition; fields from
 * that position on are excluded. A section's conditions see every field on
 * earlier pages/sections.
 */
export function answerFacts(doc: FormDocument, before: { fieldId?: string; sectionId?: string }): RuleFact[] {
  const facts: RuleFact[] = [];
  outer: for (const page of doc.pages) {
    for (const section of page.sections) {
      if (before.sectionId && section.id === before.sectionId) break outer;
      for (const field of section.fields) {
        if (before.fieldId && field.id === before.fieldId) break outer;
        if (!field.key || !CONDITIONABLE_TYPES.has(field.type)) continue;
        facts.push({
          key: `${FACT_SOURCE}.${field.key}`,
          label: field.label || field.key,
          type: factType(field),
          source: FACT_SOURCE,
          sourceLabel: FACT_SOURCE_LABEL,
          options: field.options?.items.map((item) => ({ value: item.value, label: item.label })),
        });
      }
    }
  }
  return facts;
}

/** Flat fact dict for the renderer: `answers.<key>` → current answer. */
export function answersToFacts(answers: FormAnswers): Record<string, unknown> {
  const facts: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(answers)) {
    facts[`${FACT_SOURCE}.${key}`] = value;
  }
  return facts;
}

// ---- visibility (renderer + validation shared) ----

export function sectionVisible(section: FormSection, facts: Record<string, unknown>): boolean {
  return evaluateRules(section.conditionsJson ?? null, facts);
}

export function fieldVisible(
  field: FormField,
  section: FormSection,
  facts: Record<string, unknown>,
): boolean {
  return sectionVisible(section, facts) && evaluateRules(field.conditionsJson ?? null, facts);
}

// ---- publish gate (CLIENT mirror - backend `validate_form_doc` wins) ----

function conditionFactKeys(tree: RuleGroup | null | undefined): string[] {
  if (!tree) return [];
  const keys: string[] = [];
  const walk = (group: RuleGroup) => {
    for (const rule of group.rules ?? []) {
      if (rule.kind === 'group') walk(rule);
      else {
        if (rule.fact) keys.push(rule.fact);
        if (rule.valueKind === 'fact' && typeof rule.value === 'string') keys.push(rule.value);
      }
    }
  };
  walk(tree);
  return keys;
}

/** Problems blocking publish; empty = valid. */
export function validateFormDoc(doc: FormDocument): string[] {
  const problems: string[] = [];
  if (!doc.pages || doc.pages.length === 0) {
    return ['The form needs at least one page.'];
  }

  // Duplicate / missing keys across the whole doc.
  const seenKeys = new Map<string, string>();
  const locations = allFields(doc);
  for (const { field } of locations) {
    if (isDisplayField(field)) continue;
    const key = (field.key ?? '').trim();
    const name = field.label || field.type;
    if (!key) {
      problems.push(`"${name}" is missing an answer key.`);
      continue;
    }
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) {
      problems.push(`Answer key "${key}" must be letters, digits and underscores.`);
    }
    if (seenKeys.has(key)) problems.push(`Duplicate answer key "${key}".`);
    seenKeys.set(key, field.type);
  }

  doc.pages.forEach((page, pageIndex) => {
    const fieldCount = page.sections.reduce((sum, s) => sum + s.fields.length, 0);
    if (fieldCount === 0) {
      problems.push(`Page ${pageIndex + 1} is empty.`);
    }
  });

  // Per-field rules + earlier-only condition refs, in document order.
  const earlierKeys = new Set<string>();
  // repeaterKey → {subKey: subType} for earlier repeaters (aggregate gate).
  const earlierRepeaters = new Map<string, Map<string, string>>();
  for (const page of doc.pages) {
    for (const section of page.sections) {
      for (const factKey of conditionFactKeys(section.conditionsJson)) {
        const bare = factKey.replace(/^answers\./, '');
        if (!earlierKeys.has(bare)) {
          problems.push(
            `A section condition references "${bare}", which is not an earlier field.`,
          );
        }
      }
      for (const field of section.fields) {
        const name = field.label || field.key || field.type;
        for (const factKey of conditionFactKeys(field.conditionsJson)) {
          const bare = factKey.replace(/^answers\./, '');
          if (!earlierKeys.has(bare)) {
            problems.push(
              `"${name}" has a condition referencing "${bare}", which is not an earlier field.`,
            );
          }
        }
        if (CHOICE_FIELD_TYPES.has(field.type)) {
          const items = field.options?.items ?? [];
          if (items.length === 0) problems.push(`"${name}" needs at least one option.`);
          const values = items.map((item) => item.value.trim());
          if (values.some((v) => !v)) problems.push(`"${name}" has an option without a value.`);
          if (new Set(values).size !== values.length) {
            problems.push(`"${name}" has duplicate option values.`);
          }
        }
        if (field.type === 'rating' && (field.rating?.max ?? 0) < 1) {
          problems.push(`"${name}" needs a rating scale of at least 1.`);
        }
        if (field.type === 'repeater') {
          const subs = field.repeater?.fields ?? [];
          if (subs.length === 0) problems.push(`"${name}" needs at least one sub-field.`);
          const subKeys = subs.map((s) => s.key.trim());
          if (subKeys.some((k) => !k)) problems.push(`"${name}" has a sub-field without a key.`);
          if (new Set(subKeys).size !== subKeys.length) {
            problems.push(`"${name}" has duplicate sub-field keys.`);
          }
          const { minRows, maxRows } = field.repeater ?? {};
          if (minRows != null && maxRows != null && minRows > maxRows) {
            problems.push(`"${name}" has min rows greater than max rows.`);
          }
        }
        if (field.type === 'table') {
          const cols = field.table?.columns ?? [];
          if (cols.length === 0) problems.push(`"${name}" needs at least one column.`);
          const colKeys = cols.map((c) => c.key.trim());
          if (colKeys.some((k) => !k)) problems.push(`"${name}" has a column without a key.`);
          if (new Set(colKeys).size !== colKeys.length) {
            problems.push(`"${name}" has duplicate column keys.`);
          }
          const { minRows, maxRows } = field.table ?? {};
          if (minRows != null && maxRows != null && minRows > maxRows) {
            problems.push(`"${name}" has min rows greater than max rows.`);
          }
          // Computed columns reference earlier numeric columns in the same table.
          const earlierNumericCols = new Set<string>();
          for (const col of cols) {
            if (col.type === 'computed') {
              const expr = col.computed?.expression?.trim() ?? '';
              if (!expr) {
                problems.push(`"${name}" column "${col.key}" is missing its expression.`);
              } else {
                try {
                  parseExpression(expr);
                  for (const ref of Array.from(fieldRefs(expr) ?? new Set<string>())) {
                    if (!earlierNumericCols.has(ref)) {
                      problems.push(
                        `"${name}" column "${col.key}" references "${ref}", which is not an earlier numeric column.`,
                      );
                    }
                  }
                } catch (error) {
                  problems.push(`"${name}" column "${col.key}" has an invalid expression: ${(error as Error).message}`);
                }
              }
            }
            if (col.key && ['number', 'integer', 'computed', 'fixed'].includes(col.type)) earlierNumericCols.add(col.key);
          }
        }
        if (field.type === 'computed') {
          const expression = field.computed?.expression?.trim() ?? '';
          if (!expression) {
            problems.push(`"${name}" is missing its expression.`);
          } else {
            try {
              parseExpression(expression);
              const refs = Array.from(fieldRefs(expression) ?? new Set<string>());
              for (const ref of refs) {
                if (!earlierKeys.has(ref)) {
                  problems.push(
                    `"${name}" references "${ref}", which is not an earlier field.`,
                  );
                } else if (!isNumericKey(doc, ref)) {
                  problems.push(`"${name}" references "${ref}", which is not numeric.`);
                }
              }
              // Aggregate refs (sum/avg/min/max/count over a repeater column).
              for (const agg of aggregateRefs(expression) ?? []) {
                const cols = earlierRepeaters.get(agg.repeaterKey);
                if (!cols) {
                  problems.push(
                    `"${name}" aggregates "${agg.repeaterKey}", which is not an earlier repeater field.`,
                  );
                } else if (agg.func !== 'count') {
                  if (agg.subKey === null || !cols.has(agg.subKey)) {
                    problems.push(
                      `"${name}" aggregates column "${agg.subKey}", which is not a sub-field of "${agg.repeaterKey}".`,
                    );
                  } else if (!(NUMERIC_FIELD_TYPES as Set<string>).has(cols.get(agg.subKey) ?? '')) {
                    problems.push(`"${name}" aggregates "${agg.subKey}", which is not a numeric column.`);
                  }
                }
              }
            } catch (error) {
              problems.push(
                `"${name}" has an invalid expression: ${(error as Error).message}`,
              );
            }
          }
        }
        if (field.text?.pattern) {
          try {
            void new RegExp(field.text.pattern);
          } catch {
            problems.push(`"${name}" has an invalid pattern.`);
          }
          if (!field.text.patternMessage?.trim()) {
            problems.push(`"${name}" needs a message for its pattern.`);
          }
        }
        if (field.key && isInputField(field)) {
          earlierKeys.add(field.key);
          if (field.type === 'repeater' && field.repeater) {
            earlierRepeaters.set(
              field.key,
              new Map(field.repeater.fields.filter((s) => s.key).map((s) => [s.key, s.type])),
            );
          }
          if (field.type === 'table' && field.table) {
            // Table columns are aggregatable too - `sum(table.col)`.
            earlierRepeaters.set(
              field.key,
              new Map(field.table.columns.filter((c) => c.key).map((c) => [c.key, c.type])),
            );
          }
        }
      }
    }
  }

  return problems;
}

function isNumericKey(doc: FormDocument, key: string): boolean {
  return inputFields(doc).some((f) => f.key === key && NUMERIC_FIELD_TYPES.has(f.type));
}
