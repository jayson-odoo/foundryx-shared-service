/**
 * Lead Capture field list + per-form field map helpers (lane L-D, AC-64-57).
 * Generic: any form question to any lead field the product defines. Mirrors
 * `service_backend/modules/lead_capture/{field_service,mapping}.py`.
 */
import {
  ALL_FORMS,
  type LeadField,
  type LeadFieldType,
  type LeadFormQuestion,
  type LeadSourceItem,
} from '@/types/lead-capture';

export const LEAD_FIELD_TYPE_LABELS: Record<LeadFieldType, string> = {
  name: 'Name',
  phone: 'Phone',
  email: 'Email',
  notes: 'Lead notes',
  text: 'Text',
};

export const MAX_LEAD_FIELDS = 50;
const KEY_RE = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;
const FORM_ID_RE = /^[0-9]{1,64}$/;

/** Meta standard question keys -> the field TYPE they fill when unmapped. */
const STANDARD_KEYS: Record<string, LeadFieldType> = {
  full_name: 'name',
  first_name: 'name',
  last_name: 'name',
  email: 'email',
  phone_number: 'phone',
};

/** Per-row error for the field list, or none (mirrors `field_service.set_fields`). */
export function validateLeadFields(fields: LeadField[]): Record<number, string> {
  const errors: Record<number, string> = {};
  const seen = new Map<string, number>();
  fields.forEach((f, i) => {
    if (!KEY_RE.test(f.key)) {
      errors[i] = 'Use letters, digits or _, starting with a letter.';
      return;
    }
    if (seen.has(f.key)) {
      errors[i] = 'This key is already used.';
      return;
    }
    seen.set(f.key, i);
  });
  return errors;
}

/** Instant Form ids are digits only (mirrors `form_service._check_form_id`). */
export function isFormId(value: string): boolean {
  return FORM_ID_RE.test(value.trim());
}

/** One row of the Form maps list. */
export interface FormMapRow {
  id: string;
  sourceId: string;
  pageName: string;
  formId: string;
  formName: string;
  mappedCount: number;
  /** Answers last delivered to lead notes because nothing mapped them; null = unknown. */
  unmappedCount: number | null;
  status: 'NEEDS_MAPPING' | 'MAPPED';
}

function formLabel(formId: string, formName: string | null | undefined): string {
  if (formId === ALL_FORMS) return 'All forms';
  return formName?.trim() || `Instant Form ${formId}`;
}

/** Every (Page, form) the company knows: forms with a map + forms needing one. */
export function formMapRows(sources: LeadSourceItem[]): FormMapRow[] {
  const rows: FormMapRow[] = [];
  for (const source of sources) {
    const pageName = source.pageName || source.name;
    const notices = new Map(source.needsMapping.map((n) => [n.formId, n]));
    const formIds = new Set<string>([...Object.keys(source.fieldMap ?? {}), ...Array.from(notices.keys())]);
    // "All forms" first, then the rest in form-id order.
    const ordered = Array.from(formIds).sort((a, b) =>
      a === ALL_FORMS ? -1 : b === ALL_FORMS ? 1 : a.localeCompare(b, undefined, { numeric: true }),
    );
    for (const formId of ordered) {
      const notice = notices.get(formId);
      rows.push({
        id: `${source.id}:${formId}`,
        sourceId: source.id,
        pageName,
        formId,
        formName: formLabel(formId, notice?.formName),
        mappedCount: Object.keys(source.fieldMap?.[formId] ?? {}).length,
        unmappedCount: notice ? notice.unmappedCount : null,
        status: notice ? 'NEEDS_MAPPING' : 'MAPPED',
      });
    }
  }
  return rows;
}

/**
 * The picker's starting value per question: the form's own map, else the
 * all-forms map, else '' (= no explicit map: a standard Meta question such as
 * full name / email / phone fills its field by itself, anything else goes to
 * lead notes). Mirrors `mapping.map_answers`.
 */
export function initialTargets(
  questions: LeadFormQuestion[],
  fieldMap: LeadSourceItem['fieldMap'],
  formId: string,
  fields: LeadField[],
): Record<string, string> {
  const known = new Set(fields.filter((f) => f.type !== 'notes').map((f) => f.key));
  const own = fieldMap?.[formId] ?? {};
  const base = formId === ALL_FORMS ? {} : (fieldMap?.[ALL_FORMS] ?? {});
  const out: Record<string, string> = {};
  for (const q of questions) {
    const mapped = own[q.key] ?? base[q.key];
    out[q.key] = mapped && known.has(mapped) ? mapped : '';
  }
  return out;
}

/**
 * Picker choices for ONE question: every product field except the notes one,
 * plus the '' default - named after what happens with no map: a standard Meta
 * question fills its field by itself ("Name (automatic)"), any other answer
 * stays in lead notes.
 */
export function targetOptions(
  question: LeadFormQuestion,
  fields: LeadField[],
): { value: string; label: string }[] {
  const notesLabel = fields.find((f) => f.type === 'notes')?.label || 'Lead notes';
  const std = STANDARD_KEYS[question.key];
  const auto = std ? fields.find((f) => f.type === std) : undefined;
  const fallback = auto
    ? `${auto.label || auto.key} (automatic)`
    : `Leave in ${notesLabel.toLowerCase()}`;
  return [
    { value: '', label: fallback },
    ...fields
      .filter((f) => f.type !== 'notes' && f.key !== auto?.key)
      .map((f) => ({ value: f.key, label: f.label || f.key })),
  ];
}

/** Save body: every question, '' -> null (lead notes). */
export function fieldMapPayload(
  questions: LeadFormQuestion[],
  selection: Record<string, string>,
): Record<string, string | null> {
  const out: Record<string, string | null> = {};
  for (const q of questions) out[q.key] = selection[q.key] || null;
  return out;
}
