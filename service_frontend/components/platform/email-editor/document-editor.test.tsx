/**
 * EmailEditor `surface='document'` (plan sprint-3/03 F2) — document palette
 * (table/repeater), page-setup panel, table/repeater block editors, and the
 * on-demand embedded PDF preview.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import type { RuleFact } from '@/types/rules';
import type { TemplateContextFact, TemplateDocument, TemplateListFact } from '@/types/templates';
import { createBlankDocumentDoc, createBlock, insertBlock } from '@/lib/template-doc';
import { EmailEditor } from './email-editor';

const MERGE_FIELDS: TemplateContextFact[] = [
  { key: 'companyName', label: 'Company name', sample: 'Acme' },
  { key: 'total', label: 'Total', sample: '$10.00' },
];

const LIST_FACTS: TemplateListFact[] = [
  {
    key: 'lineItems',
    label: 'Line items',
    itemFacts: [
      { key: 'description', label: 'Description', sample: 'Pass' },
      { key: 'amount', label: 'Amount', sample: '$10.00' },
    ],
  },
];

const FACTS: RuleFact[] = [];

// URL.createObjectURL / revokeObjectURL aren't in jsdom by default.
beforeAll(() => {
  (URL as unknown as { createObjectURL: () => string }).createObjectURL = vi.fn(() => 'blob:mock');
  (URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = vi.fn();
});

function docWithTable(): { doc: TemplateDocument; tableId: string } {
  let doc = createBlankDocumentDoc();
  const section = doc.sections[1];
  const table = createBlock('table');
  doc = insertBlock(doc, section.id, section.columns[0].id, table);
  return { doc, tableId: table.id };
}

function renderDoc(opts?: {
  doc?: TemplateDocument;
  onChange?: (d: TemplateDocument) => void;
  renderDocHtml?: () => Promise<string>;
  renderPdf?: () => Promise<Blob>;
}) {
  const doc = opts?.doc ?? createBlankDocumentDoc();
  const onChange = opts?.onChange ?? vi.fn();
  const renderDocHtml =
    opts?.renderDocHtml ?? vi.fn().mockResolvedValue('<!DOCTYPE html><html><body>preview</body></html>');
  const renderPdf = opts?.renderPdf ?? vi.fn().mockResolvedValue(new Blob(['%PDF-1.4'], { type: 'application/pdf' }));
  render(
    <EmailEditor
      doc={doc}
      onChange={onChange}
      editing
      surface="document"
      mergeFields={MERGE_FIELDS}
      visibilityFacts={FACTS}
      listFacts={LIST_FACTS}
      renderPreview={vi.fn()}
      renderDocHtml={renderDocHtml}
      renderPdf={renderPdf}
    />,
  );
  return { doc, onChange, renderDocHtml, renderPdf };
}

describe('EmailEditor document surface', () => {
  it('palette shows document blocks (table + repeater, no social links)', () => {
    renderDoc();
    // Search the grouped palette — 'Table' expands the Data category.
    const search = screen.getByPlaceholderText('Search blocks');
    fireEvent.change(search, { target: { value: 'Table' } });
    expect(screen.getByTestId('palette-table')).toBeInTheDocument();
    fireEvent.change(search, { target: { value: 'Repeater' } });
    expect(screen.getByTestId('palette-repeater')).toBeInTheDocument();
    // Social links is excluded from the document surface entirely.
    fireEvent.change(search, { target: { value: 'Social' } });
    expect(screen.queryByTestId('palette-socialLinks')).not.toBeInTheDocument();
  });

  it('renders the page-setup panel and edits doc.pageSetup margins', () => {
    const onChange = vi.fn();
    renderDoc({ onChange });
    expect(screen.getByTestId('page-setup-panel')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Margin top'), { target: { value: '30' } });
    const next: TemplateDocument = onChange.mock.calls.at(-1)![0];
    expect(next.pageSetup?.margins.top).toBe(30);
  });

  it('table editor binds a source + adds a column', () => {
    const { doc, tableId } = docWithTable();
    const onChange = vi.fn();
    renderDoc({ doc, onChange });
    fireEvent.click(screen.getByTestId(`canvas-block-${tableId}`));
    expect(screen.getByTestId('table-editor')).toBeInTheDocument();

    // Bind source via the SearchSelect.
    fireEvent.click(screen.getByLabelText('Table source'));
    fireEvent.click(screen.getByText('Line items'));
    let next: TemplateDocument = onChange.mock.calls.at(-1)![0];
    let block = next.sections[1].columns[0].blocks.find((b) => b.id === tableId)!;
    expect(block.type === 'table' && block.source).toBe('lineItems');

    // Add a column → 2 columns (starter has 1).
    fireEvent.click(screen.getByTestId('add-table-column'));
    next = onChange.mock.calls.at(-1)![0];
    block = next.sections[1].columns[0].blocks.find((b) => b.id === tableId)!;
    expect(block.type === 'table' && block.columns.length).toBe(2);
  });

  it('table canvas preview renders header + a sample row', () => {
    let doc = createBlankDocumentDoc();
    const section = doc.sections[1];
    const table = createBlock('table');
    if (table.type === 'table') {
      table.source = 'lineItems';
      table.columns = [{ key: 'description', header: 'Description', align: 'left', width: null }];
    }
    doc = insertBlock(doc, section.id, section.columns[0].id, table);
    renderDoc({ doc });
    const preview = screen.getByTestId(`block-table-${table.id}`);
    expect(preview).toHaveTextContent('Description');
    expect(preview).toHaveTextContent('Pass'); // sample row value
  });

  it('repeater editor binds source + adds a body block with a row.* picker', () => {
    let doc = createBlankDocumentDoc();
    const section = doc.sections[1];
    const rep = createBlock('repeater');
    if (rep.type === 'repeater') rep.source = 'lineItems';
    doc = insertBlock(doc, section.id, section.columns[0].id, rep);
    const onChange = vi.fn();
    renderDoc({ doc, onChange });

    fireEvent.click(screen.getByTestId(`canvas-block-${rep.id}`));
    expect(screen.getByTestId('repeater-editor')).toBeInTheDocument();

    // Add a Text body block (scope to the dropdown option — "Text" also
    // appears in the document palette).
    fireEvent.click(screen.getByLabelText('Add repeater block'));
    fireEvent.click(screen.getByRole('option', { name: 'Text' }));
    const next: TemplateDocument = onChange.mock.calls.at(-1)![0];
    const block = next.sections[1].columns[0].blocks.find((b) => b.id === rep.id)!;
    expect(block.type === 'repeater' && block.body.length).toBe(1);
  });

  it('repeater body merge picker offers row.* tokens of the bound source', async () => {
    let doc = createBlankDocumentDoc();
    const section = doc.sections[1];
    const rep = createBlock('repeater');
    if (rep.type === 'repeater') {
      rep.source = 'lineItems';
      const t = createBlock('text');
      rep.body = [t as never];
    }
    doc = insertBlock(doc, section.id, section.columns[0].id, rep);
    renderDoc({ doc });
    fireEvent.click(screen.getByTestId(`canvas-block-${rep.id}`));
    // The body's MergeInput picker offers row.<key> tokens of the source.
    fireEvent.click(screen.getAllByRole('button', { name: 'Insert merge field' })[0]);
    expect(await screen.findByTestId('merge-chip-row.description')).toBeInTheDocument();
    expect(screen.getByTestId('merge-chip-row.amount')).toBeInTheDocument();
  });

  it('preview mode renders the in-app HTML sheet fed by the render service', async () => {
    const renderDocHtml = vi
      .fn()
      .mockResolvedValue('<!DOCTYPE html><html><body>invoice preview</body></html>');
    renderDoc({ renderDocHtml });
    fireEvent.click(screen.getByTestId('editor-mode-preview'));
    await waitFor(() => expect(renderDocHtml).toHaveBeenCalled());
    expect(screen.getByTestId('pdf-preview-pane')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId('pdf-preview-frame')).toHaveAttribute(
        'srcdoc',
        expect.stringContaining('invoice preview'),
      ),
    );
    // Tenant content is sandboxed (scripts never run) — parity with the email pane.
    expect(screen.getByTestId('pdf-preview-frame')).toHaveAttribute('sandbox', '');
  });

  it('Refresh preview re-runs the HTML render on demand', async () => {
    const renderDocHtml = vi.fn().mockResolvedValue('<!DOCTYPE html><html><body>p</body></html>');
    renderDoc({ renderDocHtml });
    fireEvent.click(screen.getByTestId('editor-mode-preview'));
    await waitFor(() => expect(renderDocHtml).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText('Refresh preview'));
    await waitFor(() => expect(renderDocHtml).toHaveBeenCalledTimes(2));
  });
});
