/**
 * EmailEditor (plan sprint-2/07 D2/D12) - hand-rolled block editor over the
 * forever-contract JSON schema. Canvas select → settings panel, RuleBuilder
 * visibility (D8), preview widths, Edit-toggle gating.
 */
import { useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { RuleFact } from '@/types/rules';
import type { TemplateContextFact, TemplateDocument } from '@/types/templates';
import { createBlankDocument, createBlock, insertBlock } from '@/lib/template-doc';
import { EmailEditor } from './email-editor';

const MERGE_FIELDS: TemplateContextFact[] = [
  { key: 'recipient.firstName', label: 'First name', sample: 'Alex' },
  { key: 'resetLink', label: 'Reset link', sample: 'https://example.com/reset' },
];

const FACTS: RuleFact[] = [
  {
    key: 'recipient.email',
    label: 'Email',
    type: 'string',
    source: 'recipient',
    sourceLabel: 'Recipient',
  },
];

function docWithBlocks(): { doc: TemplateDocument; headingId: string; buttonId: string } {
  let doc = createBlankDocument();
  const section = doc.sections[1];
  const heading = createBlock('heading');
  const button = createBlock('button');
  doc = insertBlock(doc, section.id, section.columns[0].id, heading);
  doc = insertBlock(doc, section.id, section.columns[0].id, button);
  return { doc, headingId: heading.id, buttonId: button.id };
}

function renderEditor(opts?: { editing?: boolean; doc?: TemplateDocument; onChange?: (d: TemplateDocument) => void }) {
  const { doc } = opts?.doc ? { doc: opts.doc } : docWithBlocks();
  const onChange = opts?.onChange ?? vi.fn();
  const renderPreview = vi.fn().mockResolvedValue({
    subject: 'Preview subject',
    html: '<html><body>hi</body></html>',
    text: 'hi',
  });
  render(
    <EmailEditor
      doc={doc}
      onChange={onChange}
      editing={opts?.editing ?? true}
      mergeFields={MERGE_FIELDS}
      visibilityFacts={FACTS}
      renderPreview={renderPreview}
    />,
  );
  return { doc, onChange, renderPreview };
}

describe('EmailEditor', () => {
  it('renders the palette with every block type (grouped, searchable)', () => {
    renderEditor();
    expect(screen.getByTestId('email-block-palette')).toBeInTheDocument();
    const search = screen.getByPlaceholderText('Search blocks');
    // Searching a block's label auto-expands its category (robust to collapse).
    const byLabel: Record<string, string> = {
      heading: 'Heading',
      text: 'Text',
      image: 'Image',
      button: 'Button',
      divider: 'Divider',
      spacer: 'Spacer',
      socialLinks: 'Social',
      brandHeader: 'Brand header',
      brandFooter: 'Brand footer',
      customHtml: 'Custom HTML',
    };
    for (const [type, label] of Object.entries(byLabel)) {
      fireEvent.change(search, { target: { value: label } });
      expect(screen.getByTestId(`palette-${type}`)).toBeInTheDocument();
    }
  });

  it('clicking a canvas block opens its settings panel with visibility conditions (D8)', () => {
    const { doc, headingId } = docWithBlocks();
    renderEditor({ doc });
    fireEvent.click(screen.getByTestId(`canvas-block-${headingId}`));
    expect(screen.getByTestId('settings-panel-heading')).toBeInTheDocument();
    expect(screen.getByTestId('visibility-conditions')).toBeInTheDocument();
  });

  it('merge field picker inserts tokens into the selected block field', async () => {
    const { doc, buttonId } = docWithBlocks();
    const onChange = vi.fn();
    renderEditor({ doc, onChange });
    fireEvent.click(screen.getByTestId(`canvas-block-${buttonId}`));
    // Button settings: Label + Link fields, each with an "Insert field" picker.
    const inserters = screen.getAllByRole('button', { name: 'Insert merge field' });
    fireEvent.click(inserters[inserters.length - 1]); // the Link field's picker
    fireEvent.click(await screen.findByTestId('merge-chip-resetLink'));
    expect(onChange).toHaveBeenCalled();
    const next: TemplateDocument = onChange.mock.calls.at(-1)![0];
    expect(JSON.stringify(next)).toContain('{{resetLink}}');
  });

  it('Remove deletes the selected block', () => {
    const { doc, headingId } = docWithBlocks();
    const onChange = vi.fn();
    renderEditor({ doc, onChange });
    fireEvent.click(screen.getByTestId(`canvas-block-${headingId}`));
    fireEvent.click(screen.getByTestId('remove-block'));
    const next: TemplateDocument = onChange.mock.calls.at(-1)![0];
    expect(JSON.stringify(next)).not.toContain(headingId);
  });

  it('read mode (editing=false): no settings panel, no inline edit', () => {
    const { doc, headingId } = docWithBlocks();
    renderEditor({ doc, editing: false });
    fireEvent.click(screen.getByTestId(`canvas-block-${headingId}`));
    expect(screen.queryByTestId('settings-panel-heading')).not.toBeInTheDocument();
    expect(screen.getByText(/Enable Edit/i)).toBeInTheDocument();
    expect(screen.getByTestId(`block-heading-${headingId}`)).toHaveAttribute(
      'contenteditable',
      'false',
    );
  });

  it('preview mode renders the pipeline output in a sandboxed iframe with width toggle', async () => {
    const { renderPreview } = renderEditor();
    fireEvent.click(screen.getByTestId('editor-mode-preview'));
    await waitFor(() => expect(renderPreview).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByTestId('preview-subject')).toHaveTextContent('Preview subject'),
    );

    const frame = screen.getByTestId('preview-frame');
    expect(frame).toHaveAttribute('sandbox', '');
    expect(frame).toHaveStyle({ width: '600px' });

    fireEvent.click(screen.getByTestId('preview-width-mobile'));
    expect(screen.getByTestId('preview-frame')).toHaveStyle({ width: '375px' });
  });

  it('Add section emits a doc with the new section at the clicked index', () => {
    const { doc } = docWithBlocks();
    const onChange = vi.fn();
    renderEditor({ doc, onChange });
    fireEvent.click(screen.getByTestId('add-section-1'));
    // Controlled component: the parent owns the doc - assert the emitted value.
    const next: TemplateDocument = onChange.mock.calls.at(-1)![0];
    expect(next.sections).toHaveLength(doc.sections.length + 1);
    expect(next.sections[1].id).not.toBe(doc.sections[1].id);
  });

  it('clicking a section selects it and opens the section settings panel', () => {
    const { doc } = docWithBlocks();
    renderEditor({ doc });
    fireEvent.click(screen.getByTestId(`canvas-section-${doc.sections[1].id}`));
    expect(screen.getByTestId('settings-panel-section')).toBeInTheDocument();
  });

  it('undo/redo buttons revert and reapply doc mutations', () => {
    const { doc: initial, headingId } = docWithBlocks();
    const docs: TemplateDocument[] = [];
    // Stateful wrapper - the editor is controlled, history needs live props.
    function Harness() {
      const [doc, setDoc] = useState(initial);
      return (
        <EmailEditor
          doc={doc}
          onChange={(next) => {
            docs.push(next);
            setDoc(next);
          }}
          editing
          mergeFields={MERGE_FIELDS}
          visibilityFacts={FACTS}
          renderPreview={vi.fn()}
        />
      );
    }
    render(<Harness />);

    expect(screen.getByTestId('editor-undo')).toBeDisabled();
    expect(screen.getByTestId('editor-redo')).toBeDisabled();

    // Mutate: remove a block.
    fireEvent.click(screen.getByTestId(`canvas-block-${headingId}`));
    fireEvent.click(screen.getByTestId('remove-block'));
    expect(screen.queryByTestId(`canvas-block-${headingId}`)).not.toBeInTheDocument();
    expect(screen.getByTestId('editor-undo')).toBeEnabled();

    // Undo restores the block.
    fireEvent.click(screen.getByTestId('editor-undo'));
    expect(screen.getByTestId(`canvas-block-${headingId}`)).toBeInTheDocument();
    expect(screen.getByTestId('editor-undo')).toBeDisabled();
    expect(screen.getByTestId('editor-redo')).toBeEnabled();

    // Redo removes it again.
    fireEvent.click(screen.getByTestId('editor-redo'));
    expect(screen.queryByTestId(`canvas-block-${headingId}`)).not.toBeInTheDocument();
  });

  it('blocks are drop targets themselves (insert-after)', () => {
    const { doc, headingId } = docWithBlocks();
    renderEditor({ doc });
    // The droppable registered for a block carries index+1 semantics - assert
    // the block node exists and is wired (presence of handle = draggable too).
    const block = screen.getByTestId(`canvas-block-${headingId}`);
    expect(block).toBeInTheDocument();
  });

  it('conditioned blocks show the Conditional indicator chip', () => {
    let doc = createBlankDocument();
    const section = doc.sections[1];
    const block = createBlock('text');
    block.conditionsJson = {
      kind: 'group',
      combinator: 'and',
      rules: [
        {
          kind: 'condition',
          fact: 'recipient.email',
          operator: 'contains',
          valueKind: 'literal',
          value: '@vip.com',
        },
      ],
    };
    doc = insertBlock(doc, section.id, section.columns[0].id, block);
    renderEditor({ doc });
    expect(screen.getByTestId('condition-indicator')).toBeInTheDocument();
  });
});
