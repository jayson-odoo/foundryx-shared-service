/**
 * Form runtime validation + visibility (plan sprint-3/01, D14) - the CLIENT
 * mirror of the backend submit gate (`validate_submission`); the SERVER stays
 * the boundary (it re-derives the visible set + revalidates on submit). These
 * are PURE functions shared by the renderer (inline errors, Next-blocking) and
 * its tests.
 *
 * Visibility (D14): a field/section hides when its `conditionsJson` fails
 * against `answersToFacts(answers)` - fail-closed handled by `evaluateRules`.
 * Hidden fields KEEP their local answer (a flip-back restores it) but are
 * EXCLUDED from the visible set, from `visibleAnswers`, and from validation.
 * `required` therefore applies ONLY when visible. Computed fields are
 * never validated (read-only) but recomputed into `visibleAnswers`.
 */
import { evaluateExpression } from '@/lib/computed-expr';
import { allFields, fieldVisible, isInputField, sectionVisible } from '@/lib/form-doc';
import { isValidPhone } from '@/lib/phone';
import type {
  FormAddressAnswer,
  FormAnswers,
  FormAnswerValue,
  FormDocument,
  FormField,
  FormFieldErrors,
  FormFileAnswer,
  FormSubField,
} from '@/types/forms';

// Anchored ECMAScript email shape - pragmatic (matches the backend's loose
// check); deliverability is never asserted client-side.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// ---- visibility resolution (renderer + validation shared) ----

/**
 * The fact map conditions evaluate against - built from the VISIBLE set in
 * document order, NOT the raw answer map. This mirrors the backend
 * (`validate_submission`): a hidden field contributes NO fact, so it can't
 * keep a downstream field visible (its retained UI value is ignored for
 * conditions). Conditions reference earlier fields only (publish gate), so a
 * single document-order pass is exact - an earlier field's facts are final
 * before any later condition reads them. Computed fields contribute their
 * recomputed value.
 */
interface Resolved {
  /** Visible answers keyed by field key - computed fields recomputed. This is
   * the submit payload AND the source of condition facts. */
  clean: FormAnswers;
  /** Visible input-field keys (computed excluded). */
  visibleKeys: Set<string>;
}

/**
 * ONE document-order pass deriving the VISIBLE set, mirroring the backend
 * `validate_submission`: a field/section is visible iff its condition passes
 * against the facts of the visible fields BEFORE it (refs are backward-only,
 * publish-enforced, so one pass is exact). A hidden field contributes no fact
 * and is dropped - so a retained UI value for a hidden field can't keep a
 * downstream field visible (parity with the server; prevents a submit payload
 * the server would silently drop).
 */
function resolveVisible(doc: FormDocument, answers: FormAnswers): Resolved {
  const clean: FormAnswers = {};
  const visibleKeys = new Set<string>();
  const facts = (): Record<string, unknown> => {
    const f: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(clean)) f[`answers.${k}`] = v;
    return f;
  };
  for (const page of doc.pages) {
    for (const section of page.sections) {
      if (!sectionVisible(section, facts())) continue;
      for (const field of section.fields) {
        if (!isInputField(field) || !field.key) continue;
        if (!fieldVisible(field, section, facts())) continue;
        if (field.type === 'computed') {
          clean[field.key] = computeValue(field, clean);
          continue;
        }
        visibleKeys.add(field.key);
        if (field.key in answers) clean[field.key] = answers[field.key];
      }
    }
  }
  return { clean, visibleKeys };
}

/** The visible-set fact map (`answers.<key>`) - drives the renderer's
 * show/hide so display matches the server's visibility (D14 parity). */
export function visibleFacts(doc: FormDocument, answers: FormAnswers): Record<string, unknown> {
  const { clean } = resolveVisible(doc, answers);
  const f: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(clean)) f[`answers.${k}`] = v;
  return f;
}

/** Keys of input fields visible against `answers` (computed excluded). */
export function visibleFieldSet(doc: FormDocument, answers: FormAnswers): Set<string> {
  return resolveVisible(doc, answers).visibleKeys;
}

/**
 * The submittable answer set: hidden-field keys dropped, computed fields
 * recomputed authoritatively (server recomputes again). Visible computed
 * values land as `number | null`.
 */
export function visibleAnswers(doc: FormDocument, answers: FormAnswers): FormAnswers {
  return resolveVisible(doc, answers).clean;
}

/** Live computed value over the CURRENT (full) answer map, numeric-coerced. */
export function computeValue(field: FormField, answers: FormAnswers): number | null {
  const expr = field.computed?.expression?.trim();
  if (!expr) return null;
  const values: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(answers)) {
    // Scalars feed plain refs; arrays (repeater rows) feed aggregate functions
    // (sum/avg/min/max/count over a column) - pass them through too.
    if (typeof value === 'number' || typeof value === 'string' || Array.isArray(value)) {
      values[key] = value;
    }
  }
  return evaluateExpression(expr, values);
}

// ---- validation ----

/** Errors for one wizard page's visible fields (`{}` = clean). */
export function validatePage(
  doc: FormDocument,
  pageIndex: number,
  answers: FormAnswers,
): FormFieldErrors {
  const page = doc.pages[pageIndex];
  if (!page) return {};
  // Visible-set facts (not the raw map) so we never require a field the
  // server considers hidden - parity with validate_submission (D14).
  const facts = visibleFacts(doc, answers);
  const errors: FormFieldErrors = {};
  for (const section of page.sections) {
    if (!sectionVisible(section, facts)) continue;
    for (const field of section.fields) {
      if (!fieldVisible(field, section, facts)) continue;
      validateField(field, answers, errors);
    }
  }
  return errors;
}

/** Errors across every visible field in the document (`{}` = clean). */
export function validateAll(doc: FormDocument, answers: FormAnswers): FormFieldErrors {
  const errors: FormFieldErrors = {};
  doc.pages.forEach((_, pageIndex) => {
    Object.assign(errors, validatePage(doc, pageIndex, answers));
  });
  return errors;
}

/** The 0-based page index a field key lives on, or -1. */
export function pageOfKey(doc: FormDocument, key: string): number {
  for (const loc of allFields(doc)) {
    if (loc.field.key === key) return loc.pageIndex;
  }
  // Server error keys for repeaters are `key.row.subKey` - match the prefix.
  const bare = key.split('.')[0];
  for (const loc of allFields(doc)) {
    if (loc.field.key === bare) return loc.pageIndex;
  }
  return -1;
}

// ---- per-field validators ----

export function validateField(field: FormField, answers: FormAnswers, errors: FormFieldErrors): void {
  if (!isInputField(field) || !field.key) return;
  if (field.type === 'computed') return; // never validated (read-only)
  const key = field.key;
  const value = answers[key];

  if (field.type === 'address') {
    validateAddress(field, value, key, errors);
    return;
  }
  if (field.type === 'repeater') {
    validateRepeater(field, value, key, errors);
    return;
  }
  if (field.type === 'table') {
    validateTable(field, value, key, errors);
    return;
  }
  if (field.type === 'file') {
    validateFile(field, value, key, errors);
    return;
  }

  if (isEmpty(value)) {
    if (field.required) errors[key] = 'This field is required.';
    return;
  }

  switch (field.type) {
    case 'text':
    case 'textarea':
      validateText(field, String(value), key, errors);
      break;
    case 'email':
      if (!EMAIL_RE.test(String(value))) errors[key] = 'Enter a valid email address.';
      else validateText(field, String(value), key, errors);
      break;
    case 'url':
      if (!isValidUrl(String(value))) errors[key] = 'Enter a valid URL.';
      else validateText(field, String(value), key, errors);
      break;
    case 'phone':
      if (!isValidPhone(String(value))) errors[key] = 'Enter a valid phone number.';
      else validateText(field, String(value), key, errors);
      break;
    case 'number':
    case 'integer':
      validateNumber(field, value, key, errors);
      break;
    case 'select':
    case 'radio':
      validateChoiceMembership(field, [String(value)], key, errors);
      break;
    case 'multiselect':
    case 'checkboxes': {
      const picked = asStringArray(value);
      // Reject duplicate selections - parity with the backend
      // `_validate_multi_choice` (else the client passes but submit 422s).
      if (new Set(picked).size !== picked.length) {
        errors[key] = 'Duplicate selection.';
      } else {
        validateChoiceMembership(field, picked, key, errors);
      }
      break;
    }
    case 'yesno':
      if (typeof value !== 'boolean') errors[key] = 'Choose an option.';
      break;
    case 'date':
      if (!parsesAsDate(String(value))) errors[key] = 'Enter a valid date.';
      break;
    case 'datetime':
      if (!parsesAsDate(String(value))) errors[key] = 'Enter a valid date and time.';
      break;
    case 'rating':
      validateRating(field, value, key, errors);
      break;
    case 'signature':
      // Presence already covered by the required check above; a non-empty
      // value is an opaque data-URL string - nothing further to assert.
      break;
    default:
      break;
  }
}

function validateText(
  field: FormField,
  value: string,
  key: string,
  errors: FormFieldErrors,
): void {
  if (errors[key]) return;
  const cfg = field.text;
  if (!cfg) return;
  if (cfg.minLength != null && value.length < cfg.minLength) {
    errors[key] = `Enter at least ${cfg.minLength} characters.`;
    return;
  }
  if (cfg.maxLength != null && value.length > cfg.maxLength) {
    errors[key] = `Enter at most ${cfg.maxLength} characters.`;
    return;
  }
  if (cfg.pattern) {
    let re: RegExp | null = null;
    try {
      re = new RegExp(cfg.pattern);
    } catch {
      re = null; // invalid author pattern - fail open (publish gate caught it)
    }
    if (re && !re.test(value)) {
      errors[key] = cfg.patternMessage?.trim() || 'This value is not in the expected format.';
    }
  }
}

/** Integer / max-decimal-places enforcement (mirror of the backend). Decimals
 * are checked via a round-trip so scientific notation (1e-7) can't slip past a
 * string-digit count (code-review). */
export function numberKindError(
  _raw: unknown,
  num: number,
  integer?: boolean,
  decimals?: number,
): string | null {
  if (integer) return Number.isInteger(num) ? null : 'Enter a whole number.';
  if (decimals != null && decimals >= 0 && Number(num.toFixed(decimals)) !== num) {
    return `Enter at most ${decimals} decimal place${decimals === 1 ? '' : 's'}.`;
  }
  return null;
}

function validateNumber(
  field: FormField,
  value: FormAnswerValue,
  key: string,
  errors: FormFieldErrors,
): void {
  const num = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(num)) {
    errors[key] = 'Enter a valid number.';
    return;
  }
  const cfg = field.number;
  // `integer` field type OR the legacy number.integer flag → whole numbers.
  const kindError = numberKindError(value, num, field.type === 'integer' || cfg?.integer, cfg?.decimals);
  if (kindError) {
    errors[key] = kindError;
    return;
  }
  if (!cfg) return;
  if (cfg.min != null && num < cfg.min) {
    errors[key] = `Enter a value of at least ${cfg.min}.`;
    return;
  }
  if (cfg.max != null && num > cfg.max) {
    errors[key] = `Enter a value of at most ${cfg.max}.`;
    return;
  }
  if (cfg.step != null && cfg.step > 0) {
    const base = cfg.min ?? 0;
    const steps = (num - base) / cfg.step;
    if (Math.abs(steps - Math.round(steps)) > 1e-9) {
      errors[key] = `Enter a value in steps of ${cfg.step}.`;
    }
  }
}

function validateChoiceMembership(
  field: FormField,
  values: string[],
  key: string,
  errors: FormFieldErrors,
): void {
  const allowed = new Set((field.options?.items ?? []).map((item) => item.value));
  if (values.some((v) => !allowed.has(v))) errors[key] = 'Choose a valid option.';
}

function validateRating(
  field: FormField,
  value: FormAnswerValue,
  key: string,
  errors: FormFieldErrors,
): void {
  const num = typeof value === 'number' ? value : Number(value);
  const max = field.rating?.max ?? 5;
  if (!Number.isInteger(num) || num < 1 || num > max) errors[key] = 'Choose a rating.';
}

function validateAddress(
  field: FormField,
  value: FormAnswerValue,
  key: string,
  errors: FormFieldErrors,
): void {
  const addr = isAddress(value) ? value : null;
  const present = addr && (addr.line1 || addr.city || addr.country);
  if (!present) {
    if (field.required) errors[key] = 'This field is required.';
    return;
  }
  // When any part is filled (or it's required) the core lines are required.
  if (field.required || present) {
    if (!addr?.line1?.trim()) errors[key] = 'Address line 1 is required.';
    else if (!addr?.city?.trim()) errors[key] = 'City is required.';
    else if (!addr?.country?.trim()) errors[key] = 'Country is required.';
  }
}

function validateRepeater(
  field: FormField,
  value: FormAnswerValue,
  key: string,
  errors: FormFieldErrors,
): void {
  const rows = Array.isArray(value) ? (value as Record<string, FormAnswerValue>[]) : [];
  const realRows = rows.filter((r) => r && typeof r === 'object' && !Array.isArray(r));
  const min = field.repeater?.minRows;
  const max = field.repeater?.maxRows;

  if (realRows.length === 0) {
    if (field.required || (min != null && min > 0)) {
      errors[key] = min != null && min > 0 ? `Add at least ${min} item${min === 1 ? '' : 's'}.` : 'This field is required.';
    }
    return;
  }
  if (min != null && realRows.length < min) {
    errors[key] = `Add at least ${min} item${min === 1 ? '' : 's'}.`;
  } else if (max != null && realRows.length > max) {
    errors[key] = `Add at most ${max} item${max === 1 ? '' : 's'}.`;
  }

  const subs = field.repeater?.fields ?? [];
  realRows.forEach((row, rowIndex) => {
    for (const sub of subs) {
      validateSubField(sub, row[sub.key], `${key}.${rowIndex}.${sub.key}`, errors);
    }
  });
}

function validateTable(
  field: FormField,
  value: FormAnswerValue,
  key: string,
  errors: FormFieldErrors,
): void {
  const rows = Array.isArray(value) ? (value as Record<string, FormAnswerValue>[]) : [];
  const realRows = rows.filter((r) => r && typeof r === 'object' && !Array.isArray(r));
  const min = field.table?.minRows;
  const max = field.table?.maxRows;

  if (realRows.length === 0) {
    if (field.required || (min != null && min > 0)) {
      errors[key] = min != null && min > 0 ? `Add at least ${min} item${min === 1 ? '' : 's'}.` : 'This field is required.';
    }
    return;
  }
  if (min != null && realRows.length < min) {
    errors[key] = `Add at least ${min} item${min === 1 ? '' : 's'}.`;
  } else if (max != null && realRows.length > max) {
    errors[key] = `Add at most ${max} item${max === 1 ? '' : 's'}.`;
  }

  realRows.forEach((row, rowIndex) => {
    for (const col of field.table?.columns ?? []) {
      // computed = derived; fixed = server-stamped - neither is user input.
      if (col.type === 'computed' || col.type === 'fixed') continue;
      const errorKey = `${key}.${rowIndex}.${col.key}`;
      const cell = row[col.key];
      if (isEmpty(cell)) {
        if (col.required) errors[errorKey] = 'This field is required.';
        continue;
      }
      if (col.type === 'number' || col.type === 'integer') {
        const n = Number(cell);
        if (!Number.isFinite(n)) errors[errorKey] = 'Enter a valid number.';
        else {
          const kindError = numberKindError(cell, n, col.type === 'integer' || col.integer, col.decimals);
          if (kindError) errors[errorKey] = kindError;
          else if (col.number?.min != null && n < col.number.min) errors[errorKey] = `Enter a value of at least ${col.number.min}.`;
          else if (col.number?.max != null && n > col.number.max) errors[errorKey] = `Enter a value of at most ${col.number.max}.`;
        }
      } else if (col.type === 'date') {
        if (Number.isNaN(Date.parse(String(cell)))) errors[errorKey] = 'Enter a valid date.';
      } else if (col.type === 'select') {
        const allowed = new Set((col.options?.items ?? []).map((o) => o.value));
        if (!allowed.has(String(cell))) errors[errorKey] = 'Choose a valid option.';
      }
    }
  });
}

function validateSubField(
  sub: FormSubField,
  value: FormAnswerValue,
  errorKey: string,
  errors: FormFieldErrors,
): void {
  if (isEmpty(value)) {
    if (sub.required) errors[errorKey] = 'This field is required.';
    return;
  }
  const str = String(value);
  switch (sub.type) {
    case 'email':
      if (!EMAIL_RE.test(str)) errors[errorKey] = 'Enter a valid email address.';
      break;
    case 'url':
      if (!isValidUrl(str)) errors[errorKey] = 'Enter a valid URL.';
      break;
    case 'phone':
      if (!isValidPhone(str)) errors[errorKey] = 'Enter a valid phone number.';
      break;
    case 'number': {
      const num = Number(str);
      if (!Number.isFinite(num)) {
        errors[errorKey] = 'Enter a valid number.';
        break;
      }
      const cfg = sub.number;
      if (cfg?.min != null && num < cfg.min) errors[errorKey] = `Enter a value of at least ${cfg.min}.`;
      else if (cfg?.max != null && num > cfg.max) errors[errorKey] = `Enter a value of at most ${cfg.max}.`;
      break;
    }
    case 'date':
      if (!parsesAsDate(str)) errors[errorKey] = 'Enter a valid date.';
      break;
    case 'rating': {
      const num = Number(str);
      const max = sub.rating?.max ?? 5;
      if (!Number.isInteger(num) || num < 1 || num > max) errors[errorKey] = 'Choose a rating.';
      break;
    }
    case 'select':
    case 'radio': {
      const allowed = new Set((sub.options?.items ?? []).map((item) => item.value));
      if (!allowed.has(str)) errors[errorKey] = 'Choose a valid option.';
      break;
    }
    case 'text':
    case 'textarea': {
      const cfg = sub.text;
      if (cfg?.minLength != null && str.length < cfg.minLength) errors[errorKey] = `Enter at least ${cfg.minLength} characters.`;
      else if (cfg?.maxLength != null && str.length > cfg.maxLength) errors[errorKey] = `Enter at most ${cfg.maxLength} characters.`;
      break;
    }
    default:
      break;
  }
}

function validateFile(
  field: FormField,
  value: FormAnswerValue,
  key: string,
  errors: FormFieldErrors,
): void {
  const files = isFileList(value) ? value : [];
  if (files.length === 0) {
    if (field.required) errors[key] = 'This field is required.';
    return;
  }
  const maxCount = field.file?.maxCount;
  if (maxCount != null && files.length > maxCount) {
    errors[key] = `Attach at most ${maxCount} file${maxCount === 1 ? '' : 's'}.`;
  }
  // Per-file size/mime are enforced at pick time (the renderer rejects + shows
  // the error there); a stored answer is assumed already-validated.
}

// ---- primitive predicates / coercion ----

function isEmpty(value: FormAnswerValue | undefined): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === 'string') return value.trim() === '';
  if (Array.isArray(value)) return value.length === 0;
  return false;
}

function isValidUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}

function parsesAsDate(value: string): boolean {
  if (!value.trim()) return false;
  // Date-only ('YYYY-MM-DD') parses as UTC midnight under Date.parse; both
  // date and datetime-local strings round-trip through it.
  return !Number.isNaN(Date.parse(value));
}

function asStringArray(value: FormAnswerValue): string[] {
  return Array.isArray(value) ? value.map((v) => String(v)) : [];
}

function isAddress(value: FormAnswerValue | undefined): value is FormAddressAnswer {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function isFileList(value: FormAnswerValue | undefined): value is FormFileAnswer[] {
  return Array.isArray(value) && value.every((v) => !!v && typeof v === 'object' && 'key' in v && 'name' in v);
}
