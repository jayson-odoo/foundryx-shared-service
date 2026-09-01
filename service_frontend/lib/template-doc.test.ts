/**
 * Template block-document operations (plan sprint-2/07 D3) - the editor's
 * only mutation surface. Pure, immutable, schema-versioned.
 */
import { describe, expect, it } from 'vitest';
import {
  changeSectionLayout,
  collectMergeTokens,
  createBlankDocument,
  createBlankDocumentDoc,
  createBlock,
  createSection,
  documentValidationContext,
  findBlock,
  insertBlock,
  insertSection,
  moveBlock,
  moveSection,
  removeBlock,
  removeSection,
  updateBlock,
  validateDocument,
} from './template-doc';
import { TEMPLATE_SCHEMA_VERSION, type TemplateDocument } from '@/types/templates';

describe('template-doc', () => {
  it('blank document carries schemaVersion + brand header/footer pre-inserted (D4)', () => {
    const doc = createBlankDocument();
    expect(doc.schemaVersion).toBe(TEMPLATE_SCHEMA_VERSION);
    expect(doc.sections).toHaveLength(3);
    expect(doc.sections[0].columns[0].blocks[0].type).toBe('brandHeader');
    expect(doc.sections[2].columns[0].blocks[0].type).toBe('brandFooter');
  });

  it('insertBlock adds at index and removeBlock deletes', () => {
    let doc = createBlankDocument();
    const section = doc.sections[1];
    const block = createBlock('heading');
    doc = insertBlock(doc, section.id, section.columns[0].id, block, 0);
    expect(findBlock(doc, block.id)?.block.type).toBe('heading');

    doc = removeBlock(doc, block.id);
    expect(findBlock(doc, block.id)).toBeNull();
  });

  it('updateBlock patches immutably', () => {
    let doc = createBlankDocument();
    const section = doc.sections[1];
    const block = createBlock('heading');
    doc = insertBlock(doc, section.id, section.columns[0].id, block);
    const before = doc;
    doc = updateBlock(doc, block.id, { text: 'Hello {{recipient.firstName}}' });
    expect(before).not.toBe(doc);
    const found = findBlock(doc, block.id)?.block;
    expect(found && found.type === 'heading' ? found.text : '').toContain('{{recipient.firstName}}');
  });

  it('moveBlock repositions within a column (index shift accounted)', () => {
    let doc = createBlankDocument();
    const section = doc.sections[1];
    const colId = section.columns[0].id;
    const a = createBlock('heading');
    const b = createBlock('text');
    const c = createBlock('divider');
    doc = insertBlock(doc, section.id, colId, a);
    doc = insertBlock(doc, section.id, colId, b);
    doc = insertBlock(doc, section.id, colId, c);

    // Move a (index 0) after c (target index 3) - lands at the end.
    doc = moveBlock(doc, a.id, { sectionId: section.id, columnId: colId, index: 3 });
    const ids = doc.sections[1].columns[0].blocks.map((blk) => blk.id);
    expect(ids).toEqual([b.id, c.id, a.id]);
  });

  it('moveBlock moves across columns/sections', () => {
    let doc = createBlankDocument();
    const block = createBlock('button');
    doc = insertBlock(doc, doc.sections[1].id, doc.sections[1].columns[0].id, block);
    doc = moveBlock(doc, block.id, {
      sectionId: doc.sections[0].id,
      columnId: doc.sections[0].columns[0].id,
      index: 0,
    });
    expect(doc.sections[0].columns[0].blocks[0].id).toBe(block.id);
    expect(doc.sections[1].columns[0].blocks).toHaveLength(0);
  });

  it('changeSectionLayout folds overflow columns into the last kept column', () => {
    let doc = createBlankDocument();
    let section = createSection('50/50');
    doc = insertSection(doc, section, 1);
    const left = createBlock('text');
    const right = createBlock('image');
    doc = insertBlock(doc, section.id, section.columns[0].id, left);
    doc = insertBlock(doc, section.id, section.columns[1].id, right);

    doc = changeSectionLayout(doc, section.id, '100');
    section = doc.sections[1];
    expect(section.columns).toHaveLength(1);
    expect(section.columns[0].blocks.map((b) => b.id)).toEqual([left.id, right.id]);

    doc = changeSectionLayout(doc, section.id, '33/33/33');
    expect(doc.sections[1].columns).toHaveLength(3);
    expect(doc.sections[1].columns[1].blocks).toHaveLength(0);
  });

  it('moveSection + removeSection reorder/delete sections', () => {
    let doc = createBlankDocument();
    const ids = doc.sections.map((s) => s.id);
    doc = moveSection(doc, ids[2], 0);
    expect(doc.sections.map((s) => s.id)).toEqual([ids[2], ids[0], ids[1]]);
    doc = removeSection(doc, ids[0]);
    expect(doc.sections.map((s) => s.id)).toEqual([ids[2], ids[1]]);
  });

  it('collectMergeTokens finds tokens across subject, text, button label+href', () => {
    let doc = createBlankDocument();
    const section = doc.sections[1];
    const heading = createBlock('heading');
    if (heading.type === 'heading') heading.text = 'Hi {{recipient.firstName}}';
    const button = createBlock('button');
    if (button.type === 'button') {
      button.label = 'Open {{tenant.name}}';
      button.href = '{{resetLink}}';
    }
    doc = insertBlock(doc, section.id, section.columns[0].id, heading);
    doc = insertBlock(doc, section.id, section.columns[0].id, button);

    const tokens = collectMergeTokens(doc, 'Subject for {{recipient.email}}');
    expect(tokens).toEqual(
      new Set(['recipient.firstName', 'tenant.name', 'resetLink', 'recipient.email']),
    );
  });

  it('collectMergeTokens excludes row.* (iterator scope) and includes table footer scalars', () => {
    let doc = createBlankDocumentDoc();
    const section = doc.sections[1];
    const table = createBlock('table');
    if (table.type === 'table') {
      table.source = 'lineItems';
      table.columns = [{ key: 'amount', header: 'Amount', align: 'right', width: null }];
      table.footer = [{ cells: [{ text: 'Total {{total}}', align: 'right', span: 1 }] }];
    }
    const rep = createBlock('repeater');
    if (rep.type === 'repeater') {
      const t = createBlock('text');
      if (t.type === 'text') t.html = 'Item {{row.description}} for {{companyName}}';
      rep.source = 'lineItems';
      rep.body = [t as never];
    }
    doc = insertBlock(doc, section.id, section.columns[0].id, table);
    doc = insertBlock(doc, section.id, section.columns[0].id, rep);
    const tokens = collectMergeTokens(doc, '');
    expect(tokens.has('total')).toBe(true);
    expect(tokens.has('companyName')).toBe(true);
    expect(tokens.has('row.description')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Document surface (F2)
// ---------------------------------------------------------------------------

const INVOICE_CTX = documentValidationContext({
  facts: [
    { key: 'companyName' },
    { key: 'total' },
    { key: 'subtotal' },
  ],
  listFacts: [
    {
      key: 'lineItems',
      itemFacts: [{ key: 'description' }, { key: 'amount' }],
    },
  ],
});

function docDoc(): TemplateDocument {
  return createBlankDocumentDoc();
}

describe('document surface factories', () => {
  it('createBlankDocumentDoc carries pageSetup (A4 portrait) + brand header', () => {
    const doc = createBlankDocumentDoc();
    expect(doc.pageSetup?.size).toBe('A4');
    expect(doc.pageSetup?.orientation).toBe('portrait');
    expect(doc.sections[0].columns[0].blocks[0].type).toBe('brandHeader');
  });

  it('createBlock makes table + repeater blocks', () => {
    const table = createBlock('table');
    const rep = createBlock('repeater');
    expect(table.type).toBe('table');
    expect(rep.type).toBe('repeater');
    if (table.type === 'table') expect(table.columns).toHaveLength(1);
    if (rep.type === 'repeater') expect(rep.body).toHaveLength(0);
  });
});

describe('validateDocument (F2 D10 mirror)', () => {
  function withBlock(mutate: (b: ReturnType<typeof createBlock>) => void, type: 'table' | 'repeater') {
    let doc = docDoc();
    const section = doc.sections[1];
    const block = createBlock(type);
    mutate(block);
    doc = insertBlock(doc, section.id, section.columns[0].id, block);
    return doc;
  }

  it('a valid invoice doc has no problems', () => {
    const doc = withBlock((b) => {
      if (b.type === 'table') {
        b.source = 'lineItems';
        b.columns = [
          { key: 'description', header: 'Description', align: 'left', width: null },
          { key: 'amount', header: 'Amount', align: 'right', width: null },
        ];
        b.footer = [{ cells: [{ text: 'Total {{total}}', align: 'right', span: 1 }] }];
      }
    }, 'table');
    expect(validateDocument(doc, 'Invoice', INVOICE_CTX)).toEqual([]);
  });

  it('flags an unknown table source', () => {
    const doc = withBlock((b) => {
      if (b.type === 'table') {
        b.source = 'nope';
        b.columns = [{ key: 'x', header: 'X', align: 'left', width: null }];
      }
    }, 'table');
    expect(validateDocument(doc, '', INVOICE_CTX).join(' ')).toMatch(/not a known list field/);
  });

  it('flags a table column bound to a non-item field', () => {
    const doc = withBlock((b) => {
      if (b.type === 'table') {
        b.source = 'lineItems';
        b.columns = [{ key: 'bogus', header: 'B', align: 'left', width: null }];
      }
    }, 'table');
    expect(validateDocument(doc, '', INVOICE_CTX).join(' ')).toMatch(/"bogus" is not a field/);
  });

  it('flags a table with zero columns', () => {
    const doc = withBlock((b) => {
      if (b.type === 'table') {
        b.source = 'lineItems';
        b.columns = [];
      }
    }, 'table');
    expect(validateDocument(doc, '', INVOICE_CTX).join(' ')).toMatch(/no columns/);
  });

  it('flags row.* used inside a repeater body that is not an item field', () => {
    const doc = withBlock((b) => {
      if (b.type === 'repeater') {
        b.source = 'lineItems';
        const t = createBlock('text');
        if (t.type === 'text') t.html = '{{row.bogus}}';
        b.body = [t as never];
      }
    }, 'repeater');
    expect(validateDocument(doc, '', INVOICE_CTX).join(' ')).toMatch(/"row\.bogus" is not a field/);
  });

  it('accepts a valid row.* item field inside a repeater body', () => {
    const doc = withBlock((b) => {
      if (b.type === 'repeater') {
        b.source = 'lineItems';
        const t = createBlock('text');
        if (t.type === 'text') t.html = '{{row.description}} - {{companyName}}';
        b.body = [t as never];
      }
    }, 'repeater');
    expect(validateDocument(doc, '', INVOICE_CTX)).toEqual([]);
  });

  it('flags an empty repeater body', () => {
    const doc = withBlock((b) => {
      if (b.type === 'repeater') b.source = 'lineItems';
    }, 'repeater');
    expect(validateDocument(doc, '', INVOICE_CTX).join(' ')).toMatch(/empty body/);
  });

  it('flags row.* used OUTSIDE a table/repeater body (row-scope leak)', () => {
    let doc = docDoc();
    const section = doc.sections[1];
    const heading = createBlock('heading');
    if (heading.type === 'heading') heading.text = 'Hi {{row.description}}';
    doc = insertBlock(doc, section.id, section.columns[0].id, heading);
    expect(validateDocument(doc, '', INVOICE_CTX).join(' ')).toMatch(
      /only be used inside a table or repeater/,
    );
  });

  it('flags an unknown scalar context fact', () => {
    let doc = docDoc();
    const section = doc.sections[1];
    const heading = createBlock('heading');
    if (heading.type === 'heading') heading.text = '{{notAFact}}';
    doc = insertBlock(doc, section.id, section.columns[0].id, heading);
    expect(validateDocument(doc, '', INVOICE_CTX).join(' ')).toMatch(/Unknown merge field "{{notAFact}}"/);
  });

  it('flags page-setup problems (unknown size + negative margin)', () => {
    const doc = docDoc();
    doc.pageSetup = {
      size: 'Foolscap' as never,
      orientation: 'portrait',
      margins: { top: -1, bottom: 10, left: 10, right: 10 },
    };
    const problems = validateDocument(doc, '', INVOICE_CTX).join(' ');
    expect(problems).toMatch(/Unknown page size/);
    expect(problems).toMatch(/margin "top" must be/);
  });
});
