/**
 * Pure-op tests for the builder's immutable doc mutations (plan sprint-3/01).
 * dnd-kit pointer-sensor drags aren't unit-testable — the reorder LOGIC is, so
 * `moveField`/`moveSection`/`movePage` are exercised directly here.
 */
import { describe, expect, it } from 'vitest';
import { createField, emptyFormDoc } from '@/lib/form-doc';
import type { FormDocument } from '@/types/forms';
import {
  addOption,
  addPage,
  addSection,
  addSubField,
  changeFieldType,
  compatibleTypes,
  duplicateField,
  insertField,
  moveField,
  moveOption,
  movePage,
  moveSection,
  removeField,
  removeOption,
  removePage,
  removeSection,
  slugifyValue,
  updateField,
  updateOption,
} from './doc-ops';

function docWithTwoFields(): { doc: FormDocument; sectionId: string } {
  let doc = emptyFormDoc();
  const sectionId = doc.pages[0].sections[0].id;
  doc = insertField(doc, sectionId, 'text').doc;
  doc = insertField(doc, sectionId, 'number').doc;
  return { doc, sectionId };
}

describe('doc-ops field mutations', () => {
  it('insertField appends a field and never mutates the input', () => {
    const doc = emptyFormDoc();
    const sectionId = doc.pages[0].sections[0].id;
    const { doc: next, field } = insertField(doc, sectionId, 'email');
    expect(doc.pages[0].sections[0].fields).toHaveLength(0);
    expect(next.pages[0].sections[0].fields).toHaveLength(1);
    expect(next.pages[0].sections[0].fields[0].id).toBe(field.id);
    expect(field.type).toBe('email');
    expect(field.key).toBeTruthy();
  });

  it('updateField patches only the target', () => {
    const { doc, sectionId } = docWithTwoFields();
    const targetId = doc.pages[0].sections[0].fields[0].id;
    const next = updateField(doc, targetId, { label: 'Renamed' });
    expect(next.pages[0].sections[0].fields[0].label).toBe('Renamed');
    expect(next.pages[0].sections[0].fields[1].label).not.toBe('Renamed');
    expect(sectionId).toBeTruthy();
  });

  it('duplicateField mints a fresh id + unique key, placed after the original', () => {
    const { doc } = docWithTwoFields();
    const sourceId = doc.pages[0].sections[0].fields[0].id;
    const sourceKey = doc.pages[0].sections[0].fields[0].key;
    const { doc: next, field } = duplicateField(doc, sourceId);
    const fields = next.pages[0].sections[0].fields;
    expect(fields).toHaveLength(3);
    expect(fields[1].id).toBe(field!.id);
    expect(field!.id).not.toBe(sourceId);
    expect(field!.key).not.toBe(sourceKey);
  });

  it('removeField drops the target', () => {
    const { doc } = docWithTwoFields();
    const id = doc.pages[0].sections[0].fields[0].id;
    const next = removeField(doc, id);
    expect(next.pages[0].sections[0].fields).toHaveLength(1);
    expect(next.pages[0].sections[0].fields.find((f) => f.id === id)).toBeUndefined();
  });

  it('moveField reorders within a section', () => {
    const { doc, sectionId } = docWithTwoFields();
    const [first, second] = doc.pages[0].sections[0].fields;
    const next = moveField(doc, second.id, sectionId, 0);
    expect(next.pages[0].sections[0].fields.map((f) => f.id)).toEqual([second.id, first.id]);
  });

  it('moveField moves a field across sections', () => {
    let { doc } = docWithTwoFields();
    const pageId = doc.pages[0].id;
    doc = addSection(doc, pageId).doc;
    const targetSectionId = doc.pages[0].sections[1].id;
    const fieldId = doc.pages[0].sections[0].fields[0].id;
    const next = moveField(doc, fieldId, targetSectionId, 0);
    expect(next.pages[0].sections[0].fields).toHaveLength(1);
    expect(next.pages[0].sections[1].fields.map((f) => f.id)).toContain(fieldId);
  });
});

describe('doc-ops type switching', () => {
  it('compatibleTypes groups text family and choice family', () => {
    expect(compatibleTypes('text', 'email')).toBe(true);
    expect(compatibleTypes('select', 'radio')).toBe(true);
    expect(compatibleTypes('text', 'number')).toBe(false);
  });

  it('changeFieldType keeps the text bag within the text family', () => {
    let doc = emptyFormDoc();
    const sectionId = doc.pages[0].sections[0].id;
    doc = insertField(doc, sectionId, 'text').doc;
    const id = doc.pages[0].sections[0].fields[0].id;
    doc = updateField(doc, id, { text: { maxLength: 50 } });
    const next = changeFieldType(doc, id, 'email');
    const field = next.pages[0].sections[0].fields[0];
    expect(field.type).toBe('email');
    expect(field.text?.maxLength).toBe(50);
  });

  it('changeFieldType resets incompatible bags and seeds defaults', () => {
    let doc = emptyFormDoc();
    const sectionId = doc.pages[0].sections[0].id;
    doc = insertField(doc, sectionId, 'text').doc;
    const id = doc.pages[0].sections[0].fields[0].id;
    const next = changeFieldType(doc, id, 'select');
    const field = next.pages[0].sections[0].fields[0];
    expect(field.type).toBe('select');
    expect(field.options?.items.length).toBeGreaterThan(0);
    expect(field.key).toBeTruthy();
  });

  it('changeFieldType to a display type drops the answer key', () => {
    let doc = emptyFormDoc();
    const sectionId = doc.pages[0].sections[0].id;
    doc = insertField(doc, sectionId, 'text').doc;
    const id = doc.pages[0].sections[0].fields[0].id;
    const next = changeFieldType(doc, id, 'heading');
    expect(next.pages[0].sections[0].fields[0].key).toBeUndefined();
  });
});

describe('doc-ops option editor', () => {
  function choiceDoc() {
    let doc = emptyFormDoc();
    const sectionId = doc.pages[0].sections[0].id;
    doc = insertField(doc, sectionId, 'select').doc;
    return { doc, fieldId: doc.pages[0].sections[0].fields[0].id };
  }

  it('slugifyValue produces a clean slug', () => {
    expect(slugifyValue('Hot Dog!')).toBe('hot_dog');
    expect(slugifyValue('   ')).toBe('option');
  });

  it('addOption derives a unique value from the label', () => {
    const { doc, fieldId } = choiceDoc();
    const next = addOption(doc, fieldId, 'Extra Cheese');
    const items = next.pages[0].sections[0].fields[0].options!.items;
    expect(items[items.length - 1]).toEqual({ value: 'extra_cheese', label: 'Extra Cheese' });
  });

  it('updateOption / removeOption / moveOption work', () => {
    const { doc, fieldId } = choiceDoc();
    let next = updateOption(doc, fieldId, 0, { label: 'First' });
    expect(next.pages[0].sections[0].fields[0].options!.items[0].label).toBe('First');
    next = moveOption(next, fieldId, 0, 1);
    expect(next.pages[0].sections[0].fields[0].options!.items[0].label).toBe('Option 2');
    next = removeOption(next, fieldId, 0);
    expect(next.pages[0].sections[0].fields[0].options!.items).toHaveLength(1);
  });
});

describe('doc-ops repeater', () => {
  it('addSubField appends a sub-field with a unique key', () => {
    let doc = emptyFormDoc();
    const sectionId = doc.pages[0].sections[0].id;
    doc = insertField(doc, sectionId, 'repeater').doc;
    const fieldId = doc.pages[0].sections[0].fields[0].id;
    const before = doc.pages[0].sections[0].fields[0].repeater!.fields.length;
    const next = addSubField(doc, fieldId, 'number');
    const subs = next.pages[0].sections[0].fields[0].repeater!.fields;
    expect(subs).toHaveLength(before + 1);
    expect(new Set(subs.map((s) => s.key)).size).toBe(subs.length);
  });
});

describe('doc-ops sections and pages', () => {
  it('addSection / removeSection', () => {
    let doc = emptyFormDoc();
    const pageId = doc.pages[0].id;
    doc = addSection(doc, pageId).doc;
    expect(doc.pages[0].sections).toHaveLength(2);
    const removeId = doc.pages[0].sections[1].id;
    doc = removeSection(doc, removeId);
    expect(doc.pages[0].sections).toHaveLength(1);
  });

  it('moveSection reorders within a page', () => {
    let doc = emptyFormDoc();
    const pageId = doc.pages[0].id;
    doc = addSection(doc, pageId).doc;
    const ids = doc.pages[0].sections.map((s) => s.id);
    const next = moveSection(doc, pageId, 0, 1);
    expect(next.pages[0].sections.map((s) => s.id)).toEqual([ids[1], ids[0]]);
  });

  it('addPage / movePage / removePage; never goes below one page', () => {
    let doc = emptyFormDoc();
    doc = addPage(doc).doc;
    expect(doc.pages).toHaveLength(2);
    const ids = doc.pages.map((p) => p.id);
    let next = movePage(doc, 0, 1);
    expect(next.pages.map((p) => p.id)).toEqual([ids[1], ids[0]]);
    next = removePage(next, next.pages[0].id);
    expect(next.pages).toHaveLength(1);
    // Cannot remove the last remaining page.
    const guarded = removePage(next, next.pages[0].id);
    expect(guarded.pages).toHaveLength(1);
  });
});

describe('doc-ops immutability', () => {
  it('createField is preserved as a building block', () => {
    const doc = emptyFormDoc();
    const field = createField(doc, 'rating');
    expect(field.rating?.max).toBe(5);
  });
});
