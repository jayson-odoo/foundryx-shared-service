/**
 * MergeFieldEditor - click-to-insert variable chips + live preview
 * (sprint-2/01 review mandate: no hand-typed {{tokens}}).
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MergeFieldEditor, renderTemplate } from './merge-field-editor';

const FIELDS = [
  { key: 'recordLabel', label: 'Record name' },
  { key: 'toStatus', label: 'To status' },
];

const CONTEXT = { recordLabel: 'Acme Events', toStatus: 'Approved' };

describe('renderTemplate', () => {
  it('substitutes known fields and blanks unknown ones', () => {
    expect(renderTemplate('{{recordLabel}} → {{toStatus}} {{nope}}', CONTEXT)).toBe(
      'Acme Events → Approved ',
    );
  });
});

describe('MergeFieldEditor', () => {
  function setup() {
    const onSubjectChange = vi.fn();
    const onBodyChange = vi.fn();
    render(
      <MergeFieldEditor
        subject=""
        body="Hello "
        onSubjectChange={onSubjectChange}
        onBodyChange={onBodyChange}
        fields={FIELDS}
        previewContext={CONTEXT}
        subjectPlaceholder="Subject…"
        bodyPlaceholder="Body…"
      />,
    );
    return { onSubjectChange, onBodyChange };
  }

  it('inserts a token into the body (default target) on chip click', () => {
    const { onBodyChange } = setup();
    fireEvent.click(screen.getByRole('button', { name: 'Insert Record name' }));
    expect(onBodyChange).toHaveBeenCalledWith('Hello {{recordLabel}}');
  });

  it('inserts into the subject when it was focused last', () => {
    const { onSubjectChange } = setup();
    fireEvent.focus(screen.getByPlaceholderText('Subject…'));
    fireEvent.click(screen.getByRole('button', { name: 'Insert To status' }));
    expect(onSubjectChange).toHaveBeenCalledWith('{{toStatus}}');
  });

  it('preview swaps IN-PLACE: same boxes render values, toggle back to edit', async () => {
    render(
      <MergeFieldEditor
        subject="{{recordLabel}} moved"
        body="Now {{toStatus}}."
        onSubjectChange={vi.fn()}
        onBodyChange={vi.fn()}
        fields={FIELDS}
        previewContext={CONTEXT}
        subjectPlaceholder="Subject…"
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => {
      const preview = screen.getByTestId('template-preview');
      expect(preview).toHaveTextContent('Acme Events moved');
      expect(preview).toHaveTextContent('Now Approved.');
    });
    // The edit boxes are REPLACED, not duplicated below.
    expect(screen.queryByPlaceholderText('Subject…')).not.toBeInTheDocument();

    // Toggle back restores editing.
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    expect(screen.getByPlaceholderText('Subject…')).toBeInTheDocument();
    expect(screen.queryByTestId('template-preview')).not.toBeInTheDocument();
  });
});
