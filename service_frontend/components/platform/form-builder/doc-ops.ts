/**
 * Pure immutable mutations over the form block document (plan sprint-3/01
 * D6/D7) — the editor's write layer. `lib/form-doc.ts` is off-limits to this
 * session, so the builder's structural edits live here as pure functions
 * (every one returns a NEW document) so `useHistory` keeps a faithful
 * snapshot timeline (workflow-doc / template-doc precedent).
 *
 * Helpers never mutate their inputs and never call `fetch`/eval. Choice
 * option values are slugged from labels at insert (D8 static-only); type
 * switches preserve compatible config bags (text↔text, choice↔choice) and
 * reset the rest (D7 quick type-switch).
 */
import {
  CHOICE_FIELD_TYPES,
  createField,
  createPage,
  createSection,
  createSubField,
  DISPLAY_FIELD_TYPES,
  newId,
  suggestKey,
} from '@/lib/form-doc';
import type {
  FormChoiceItem,
  FormDocument,
  FormField,
  FormFieldType,
  FormInputFieldType,
  FormPage,
  FormSection,
  FormSubField,
  FormSubFieldType,
} from '@/types/forms';

// ---- the families that survive a quick type-switch (D7) ----

/** Text-family input types — switch between these keeps the `text` bag. */
export const TEXT_FAMILY: ReadonlySet<FormFieldType> = new Set<FormFieldType>([
  'text',
  'textarea',
  'email',
  'phone',
  'url',
]);

/** True when `from`→`to` may keep its type-specific config bag. */
export function compatibleTypes(from: FormFieldType, to: FormFieldType): boolean {
  if (from === to) return true;
  if (TEXT_FAMILY.has(from) && TEXT_FAMILY.has(to)) return true;
  if (CHOICE_FIELD_TYPES.has(from) && CHOICE_FIELD_TYPES.has(to)) return true;
  return false;
}

// ---- option-value slug (D8) ----

/** Lowercase, underscore-joined, alnum-only slug for a fresh option value. */
export function slugifyValue(label: string): string {
  const slug = label
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
  return slug || 'option';
}

// ---- internal field map helpers (immutable) ----

function mapPages(doc: FormDocument, fn: (page: FormPage) => FormPage): FormDocument {
  return { ...doc, pages: doc.pages.map(fn) };
}

function mapSections(
  doc: FormDocument,
  fn: (section: FormSection) => FormSection,
): FormDocument {
  return mapPages(doc, (page) => ({ ...page, sections: page.sections.map(fn) }));
}

function mapFieldInSection(
  section: FormSection,
  fieldId: string,
  fn: (field: FormField) => FormField,
): FormSection {
  if (!section.fields.some((f) => f.id === fieldId)) return section;
  return { ...section, fields: section.fields.map((f) => (f.id === fieldId ? fn(f) : f)) };
}

// ---- locate helpers ----

export function sectionOf(doc: FormDocument, fieldId: string): FormSection | null {
  for (const page of doc.pages) {
    for (const section of page.sections) {
      if (section.fields.some((f) => f.id === fieldId)) return section;
    }
  }
  return null;
}

/** First section id of the doc (fallback drop target for click-to-add). */
export function lastSectionId(doc: FormDocument): string | null {
  const pages = doc.pages;
  if (pages.length === 0) return null;
  const page = pages[pages.length - 1];
  if (page.sections.length === 0) return null;
  return page.sections[page.sections.length - 1].id;
}

// ---- field mutations ----

export function updateField(
  doc: FormDocument,
  fieldId: string,
  patch: Partial<FormField>,
): FormDocument {
  return mapSections(doc, (section) =>
    mapFieldInSection(section, fieldId, (field) => ({ ...field, ...patch })),
  );
}

/** Append a fresh field of `type` to a section (click-to-add). */
export function insertField(
  doc: FormDocument,
  sectionId: string,
  type: FormFieldType,
  index?: number,
): { doc: FormDocument; field: FormField } {
  const field = createField(doc, type);
  const next = mapSections(doc, (section) => {
    if (section.id !== sectionId) return section;
    const fields = [...section.fields];
    const at = index ?? fields.length;
    fields.splice(at, 0, field);
    return { ...section, fields };
  });
  return { doc: next, field };
}

/** Duplicate a field with a fresh id + unique key, placed after the original. */
export function duplicateField(doc: FormDocument, fieldId: string): { doc: FormDocument; field: FormField | null } {
  const source = sectionOf(doc, fieldId);
  if (!source) return { doc, field: null };
  const original = source.fields.find((f) => f.id === fieldId);
  if (!original) return { doc, field: null };
  const clone: FormField = {
    ...structuredClone(original),
    id: newId('fld'),
  };
  if (!DISPLAY_FIELD_TYPES.has(clone.type) && clone.key) {
    clone.key = suggestKey(doc, clone.type as FormInputFieldType);
  }
  if (clone.repeater) {
    clone.repeater = {
      ...clone.repeater,
      fields: clone.repeater.fields.map((sub) => ({ ...sub, id: newId('sub') })),
    };
  }
  const next = mapSections(doc, (section) => {
    if (section.id !== source.id) return section;
    const idx = section.fields.findIndex((f) => f.id === fieldId);
    const fields = [...section.fields];
    fields.splice(idx + 1, 0, clone);
    return { ...section, fields };
  });
  return { doc: next, field: clone };
}

export function removeField(doc: FormDocument, fieldId: string): FormDocument {
  return mapSections(doc, (section) =>
    section.fields.some((f) => f.id === fieldId)
      ? { ...section, fields: section.fields.filter((f) => f.id !== fieldId) }
      : section,
  );
}

/**
 * Move a field to `targetSectionId` at `index`. Within-section reorder and
 * cross-section move both flow through here (sortable drop).
 */
export function moveField(
  doc: FormDocument,
  fieldId: string,
  targetSectionId: string,
  index: number,
): FormDocument {
  const from = sectionOf(doc, fieldId);
  if (!from) return doc;
  const field = from.fields.find((f) => f.id === fieldId);
  if (!field) return doc;

  // Same-section reorder: splice within the one array (index is post-removal).
  if (from.id === targetSectionId) {
    return mapSections(doc, (section) => {
      if (section.id !== targetSectionId) return section;
      const without = section.fields.filter((f) => f.id !== fieldId);
      const clamped = Math.max(0, Math.min(index, without.length));
      without.splice(clamped, 0, field);
      return { ...section, fields: without };
    });
  }

  return mapSections(doc, (section) => {
    if (section.id === from.id) {
      return { ...section, fields: section.fields.filter((f) => f.id !== fieldId) };
    }
    if (section.id === targetSectionId) {
      const fields = [...section.fields];
      const clamped = Math.max(0, Math.min(index, fields.length));
      fields.splice(clamped, 0, field);
      return { ...section, fields };
    }
    return section;
  });
}

/**
 * Quick type-switch (D7): change a field's type, keeping id/key/label/required
 * + the config bag when compatible, resetting the type-specific bags
 * otherwise. Display↔input swaps reset key presence too.
 */
export function changeFieldType(
  doc: FormDocument,
  fieldId: string,
  toType: FormFieldType,
): FormDocument {
  return mapSections(doc, (section) =>
    mapFieldInSection(section, fieldId, (field) => {
      if (field.type === toType) return field;
      const keep = compatibleTypes(field.type, toType);
      const next: FormField = {
        id: field.id,
        type: toType,
        label: field.label,
        required: field.required,
        placeholder: field.placeholder,
        helpText: field.helpText,
        conditionsJson: field.conditionsJson,
      };
      // Answer key: keep for input→input, mint for display→input, drop for →display.
      if (DISPLAY_FIELD_TYPES.has(toType)) {
        delete next.key;
      } else {
        next.key = field.key ?? suggestKey(doc, toType as FormInputFieldType);
      }
      if (keep) {
        if (TEXT_FAMILY.has(toType)) next.text = field.text;
        if (CHOICE_FIELD_TYPES.has(toType)) next.options = field.options;
      } else {
        // Seed sensible defaults from a fresh field of the new type.
        const template = createField(doc, toType);
        if (template.options) next.options = template.options;
        if (template.rating) next.rating = template.rating;
        if (template.heading) next.heading = template.heading;
        if (template.repeater) next.repeater = template.repeater;
        if (template.table) next.table = template.table;
        if (template.computed) next.computed = template.computed;
      }
      return next;
    }),
  );
}

// ---- choice-option editor (D8) ----

export function addOption(doc: FormDocument, fieldId: string, label?: string): FormDocument {
  return updateFieldOptions(doc, fieldId, (items) => {
    const text = label?.trim() || `Option ${items.length + 1}`;
    const used = new Set(items.map((i) => i.value));
    let value = slugifyValue(text);
    for (let i = 2; used.has(value); i += 1) value = `${slugifyValue(text)}_${i}`;
    return [...items, { value, label: text }];
  });
}

export function updateOption(
  doc: FormDocument,
  fieldId: string,
  index: number,
  patch: Partial<FormChoiceItem>,
): FormDocument {
  return updateFieldOptions(doc, fieldId, (items) =>
    items.map((item, i) => (i === index ? { ...item, ...patch } : item)),
  );
}

export function removeOption(doc: FormDocument, fieldId: string, index: number): FormDocument {
  return updateFieldOptions(doc, fieldId, (items) => items.filter((_, i) => i !== index));
}

export function moveOption(
  doc: FormDocument,
  fieldId: string,
  index: number,
  direction: -1 | 1,
): FormDocument {
  return updateFieldOptions(doc, fieldId, (items) => {
    const target = index + direction;
    if (target < 0 || target >= items.length) return items;
    const next = [...items];
    [next[index], next[target]] = [next[target], next[index]];
    return next;
  });
}

function updateFieldOptions(
  doc: FormDocument,
  fieldId: string,
  fn: (items: FormChoiceItem[]) => FormChoiceItem[],
): FormDocument {
  return mapSections(doc, (section) =>
    mapFieldInSection(section, fieldId, (field) => ({
      ...field,
      options: { kind: 'static', items: fn(field.options?.items ?? []) },
    })),
  );
}

// ---- repeater sub-fields (D7) ----

export function addSubField(
  doc: FormDocument,
  fieldId: string,
  type: FormSubFieldType,
): FormDocument {
  return mapSections(doc, (section) =>
    mapFieldInSection(section, fieldId, (field) => {
      const existing = field.repeater?.fields ?? [];
      const sub = createSubField(existing, type);
      return {
        ...field,
        repeater: { ...(field.repeater ?? {}), fields: [...existing, sub] },
      };
    }),
  );
}

export function updateSubField(
  doc: FormDocument,
  fieldId: string,
  subId: string,
  patch: Partial<FormSubField>,
): FormDocument {
  return mapSections(doc, (section) =>
    mapFieldInSection(section, fieldId, (field) => ({
      ...field,
      repeater: field.repeater
        ? {
            ...field.repeater,
            fields: field.repeater.fields.map((sub) =>
              sub.id === subId ? { ...sub, ...patch } : sub,
            ),
          }
        : field.repeater,
    })),
  );
}

export function removeSubField(doc: FormDocument, fieldId: string, subId: string): FormDocument {
  return mapSections(doc, (section) =>
    mapFieldInSection(section, fieldId, (field) => ({
      ...field,
      repeater: field.repeater
        ? { ...field.repeater, fields: field.repeater.fields.filter((s) => s.id !== subId) }
        : field.repeater,
    })),
  );
}

export function moveSubField(
  doc: FormDocument,
  fieldId: string,
  subId: string,
  direction: -1 | 1,
): FormDocument {
  return mapSections(doc, (section) =>
    mapFieldInSection(section, fieldId, (field) => {
      const subs = field.repeater?.fields ?? [];
      const idx = subs.findIndex((s) => s.id === subId);
      const target = idx + direction;
      if (idx === -1 || target < 0 || target >= subs.length) return field;
      const next = [...subs];
      [next[idx], next[target]] = [next[target], next[idx]];
      return { ...field, repeater: { ...field.repeater!, fields: next } };
    }),
  );
}

// ---- section mutations ----

export function updateSection(
  doc: FormDocument,
  sectionId: string,
  patch: Partial<FormSection>,
): FormDocument {
  return mapSections(doc, (section) =>
    section.id === sectionId ? { ...section, ...patch } : section,
  );
}

export function addSection(doc: FormDocument, pageId: string): { doc: FormDocument; section: FormSection } {
  const section = createSection();
  const next = mapPages(doc, (page) =>
    page.id === pageId ? { ...page, sections: [...page.sections, section] } : page,
  );
  return { doc: next, section };
}

export function removeSection(doc: FormDocument, sectionId: string): FormDocument {
  return mapPages(doc, (page) => ({
    ...page,
    sections: page.sections.filter((s) => s.id !== sectionId),
  }));
}

export function moveSection(
  doc: FormDocument,
  pageId: string,
  fromIndex: number,
  toIndex: number,
): FormDocument {
  return mapPages(doc, (page) => {
    if (page.id !== pageId) return page;
    const sections = [...page.sections];
    if (fromIndex < 0 || fromIndex >= sections.length) return page;
    const [moved] = sections.splice(fromIndex, 1);
    const clamped = Math.max(0, Math.min(toIndex, sections.length));
    sections.splice(clamped, 0, moved);
    return { ...page, sections };
  });
}

// ---- page mutations ----

export function updatePage(doc: FormDocument, pageId: string, patch: Partial<FormPage>): FormDocument {
  return mapPages(doc, (page) => (page.id === pageId ? { ...page, ...patch } : page));
}

export function addPage(doc: FormDocument): { doc: FormDocument; page: FormPage } {
  const page = createPage();
  return { doc: { ...doc, pages: [...doc.pages, page] }, page };
}

export function removePage(doc: FormDocument, pageId: string): FormDocument {
  // Never leave the document page-less (the publish gate requires one).
  if (doc.pages.length <= 1) return doc;
  return { ...doc, pages: doc.pages.filter((p) => p.id !== pageId) };
}

export function movePage(doc: FormDocument, fromIndex: number, toIndex: number): FormDocument {
  const pages = [...doc.pages];
  if (fromIndex < 0 || fromIndex >= pages.length) return doc;
  const [moved] = pages.splice(fromIndex, 1);
  const clamped = Math.max(0, Math.min(toIndex, pages.length));
  pages.splice(clamped, 0, moved);
  return { ...doc, pages };
}
