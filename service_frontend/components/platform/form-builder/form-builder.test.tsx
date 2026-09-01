/**
 * FormBuilder component tests (plan sprint-3/01) - palette click-to-add per
 * category, field-config edits flowing into the doc, duplicate-key warning,
 * options/repeater editors, computed-expression error, conditions RuleBuilder
 * mount, undo/redo, and the read-only (editing=false) render. dnd-kit
 * pointer-sensor drags aren't drivable in jsdom - the reorder logic is covered
 * by doc-ops.test.ts.
 */
import { useState } from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { createField, emptyFormDoc } from '@/lib/form-doc';
import type { FormDocument } from '@/types/forms';
import { FormBuilder } from './form-builder';

/** Controlled host so onChange round-trips into props (real ResourceForm shape). */
function Host({ initial, editing = true }: { initial?: FormDocument; editing?: boolean }) {
  const [doc, setDoc] = useState<FormDocument>(initial ?? emptyFormDoc());
  return <FormBuilder doc={doc} onChange={setDoc} editing={editing} />;
}

function docWithTextField(): FormDocument {
  const doc = emptyFormDoc();
  const field = createField(doc, 'text');
  doc.pages[0].sections[0].fields.push(field);
  return doc;
}

describe('FormBuilder palette', () => {
  it('expands a category and click-adds a field of that type', () => {
    render(<Host />);
    // Number category collapsed by default - expand it.
    fireEvent.click(screen.getByTestId('palette-category-number'));
    fireEvent.click(screen.getByTestId('palette-number'));
    // A number field row now exists on the canvas.
    expect(screen.getByTestId('form-canvas').querySelector('[data-field-type="number"]')).toBeTruthy();
  });

  it('search filters the palette and auto-expands matches', () => {
    render(<Host />);
    fireEvent.change(screen.getByLabelText('Search fields'), { target: { value: 'rating' } });
    expect(screen.getByTestId('palette-rating')).toBeInTheDocument();
    expect(screen.queryByTestId('palette-email')).not.toBeInTheDocument();
  });

  it('hides the palette and inputs in read-only mode', () => {
    render(<Host initial={docWithTextField()} editing={false} />);
    expect(screen.queryByTestId('form-palette')).not.toBeInTheDocument();
    expect(screen.queryByTestId('field-label')).not.toBeInTheDocument();
  });
});

describe('FormBuilder field settings', () => {
  it('selecting a field then editing its label updates the doc', () => {
    render(<Host initial={docWithTextField()} />);
    const row = screen.getByTestId('form-canvas').querySelector('[data-field-type="text"]') as HTMLElement;
    fireEvent.click(row);
    const labelInput = screen.getByTestId('field-label');
    fireEvent.change(labelInput, { target: { value: 'Full name' } });
    // The canvas preview reflects the new label.
    expect(screen.getByTestId('form-canvas')).toHaveTextContent('Full name');
  });

  it('warns on a duplicate answer key', () => {
    const doc = emptyFormDoc();
    const a = createField(doc, 'text');
    a.key = 'name';
    const b = createField(doc, 'text');
    b.key = 'email';
    doc.pages[0].sections[0].fields.push(a, b);
    render(<Host initial={doc} />);
    const rows = screen.getByTestId('form-canvas').querySelectorAll('[data-field-type="text"]');
    fireEvent.click(rows[1]);
    fireEvent.change(screen.getByTestId('field-key'), { target: { value: 'name' } });
    expect(screen.getByTestId('key-duplicate')).toBeInTheDocument();
  });

  it('options editor adds and removes a choice option', () => {
    const doc = emptyFormDoc();
    doc.pages[0].sections[0].fields.push(createField(doc, 'select'));
    render(<Host initial={doc} />);
    fireEvent.click(screen.getByTestId('form-canvas').querySelector('[data-field-type="select"]') as HTMLElement);
    const editor = screen.getByTestId('options-editor');
    expect(within(editor).getAllByTestId(/^option-label-/)).toHaveLength(2);
    fireEvent.click(screen.getByTestId('option-add'));
    expect(within(screen.getByTestId('options-editor')).getAllByTestId(/^option-label-/)).toHaveLength(3);
    fireEvent.click(within(screen.getByTestId('options-editor')).getByTestId('option-remove-0'));
    expect(within(screen.getByTestId('options-editor')).getAllByTestId(/^option-label-/)).toHaveLength(2);
  });

  it('repeater sub-field editor adds a sub-field', () => {
    const doc = emptyFormDoc();
    doc.pages[0].sections[0].fields.push(createField(doc, 'repeater'));
    render(<Host initial={doc} />);
    fireEvent.click(screen.getByTestId('form-canvas').querySelector('[data-field-type="repeater"]') as HTMLElement);
    const editor = screen.getByTestId('subfield-editor');
    const before = within(editor).getAllByLabelText(/Sub-field \d+ key/).length;
    // The "Add sub-field…" combobox; open, search to disambiguate, pick a type.
    fireEvent.click(within(editor).getByLabelText('Add sub-field type'));
    const search = screen.getAllByPlaceholderText('Search…').at(-1)!;
    fireEvent.change(search, { target: { value: 'Number' } });
    fireEvent.click(screen.getByRole('option', { name: /Number/ }));
    expect(within(screen.getByTestId('subfield-editor')).getAllByLabelText(/Sub-field \d+ key/).length).toBe(
      before + 1,
    );
  });

  it('shows a computed-expression error for invalid syntax', () => {
    const doc = emptyFormDoc();
    doc.pages[0].sections[0].fields.push(createField(doc, 'computed'));
    render(<Host initial={doc} />);
    fireEvent.click(screen.getByTestId('form-canvas').querySelector('[data-field-type="computed"]') as HTMLElement);
    fireEvent.change(screen.getByTestId('computed-expression'), { target: { value: '1 +' } });
    expect(screen.getByTestId('computed-error')).toBeInTheDocument();
  });
});

describe('FormBuilder section conditions', () => {
  it('mounts the RuleBuilder for a selected section', () => {
    render(<Host initial={docWithTextField()} />);
    const section = screen.getByTestId('form-canvas').querySelector('[data-testid^="section-card-"]') as HTMLElement;
    fireEvent.click(section);
    expect(screen.getByTestId('settings-section')).toHaveTextContent('Visible when');
  });
});

describe('FormBuilder undo/redo', () => {
  it('undo restores the previous doc, redo re-applies', () => {
    render(<Host />);
    // Add a heading via the palette (Display category).
    fireEvent.click(screen.getByTestId('palette-category-display'));
    fireEvent.click(screen.getByTestId('palette-heading'));
    expect(screen.getByTestId('form-canvas').querySelector('[data-field-type="heading"]')).toBeTruthy();

    fireEvent.click(screen.getByTestId('form-undo'));
    expect(screen.getByTestId('form-canvas').querySelector('[data-field-type="heading"]')).toBeFalsy();

    fireEvent.click(screen.getByTestId('form-redo'));
    expect(screen.getByTestId('form-canvas').querySelector('[data-field-type="heading"]')).toBeTruthy();
  });
});

describe('FormBuilder empty state', () => {
  it('shows the select-a-field status when nothing is selected', () => {
    render(<Host />);
    expect(screen.getByTestId('settings-empty')).toHaveTextContent('Select a field to configure');
  });
});
