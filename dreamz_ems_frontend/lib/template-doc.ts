import {
  SECTION_LAYOUT_COLUMNS,
  TEMPLATE_SCHEMA_VERSION,
  type PageSetup,
  type RepeaterBodyBlock,
  type SectionLayout,
  type TemplateBlock,
  type TemplateBlockType,
  type TemplateColumn,
  type TemplateDocument,
  type TemplateSection,
} from '@/types/templates';

/** Stable short id for blocks/sections/columns (forever-contract ids — D3). */
export function newDocId(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 8)}`;
}

export const DEFAULT_PADDING = { top: 16, bottom: 16, left: 24, right: 24 };

/** Factory: a new block of the given type with house defaults. */
export function createBlock(type: TemplateBlockType): TemplateBlock {
  const id = newDocId('blk');
  switch (type) {
    case 'heading':
      return { id, type, text: 'Heading', level: 2, align: 'left' };
    case 'text':
      return { id, type, html: 'Write something…', align: 'left' };
    case 'image':
      return { id, type, storageKey: null, src: null, alt: '', width: null, align: 'center', href: null };
    case 'button':
      return {
        id,
        type,
        label: 'Click me',
        href: '',
        align: 'left',
        backgroundColor: null,
        textColor: null,
        borderRadius: 6,
      };
    case 'divider':
      return { id, type, color: '#E4E4E7', thickness: 1 };
    case 'spacer':
      return { id, type, height: 24 };
    case 'socialLinks':
      return { id, type, links: null, align: 'center', iconSize: 24 };
    case 'brandHeader':
      return { id, type, overrides: null };
    case 'brandFooter':
      return { id, type, overrides: null };
    case 'customHtml':
      return { id, type, html: '' };
    case 'qr':
      return { id, type, data: '', ecLevel: 'M', size: 120, align: 'center' };
    // F2 document blocks — empty source (bound in the panel) + a starter column.
    case 'table':
      return {
        id,
        type,
        source: '',
        columns: [{ key: '', header: 'Column', align: 'left', width: null }],
        footer: null,
      };
    case 'repeater':
      return { id, type, source: '', body: [] };
  }
}

/** Default A4 portrait page setup (mm) for a new document template (D3). */
export const DEFAULT_PAGE_SETUP: PageSetup = {
  size: 'A4',
  orientation: 'portrait',
  margins: { top: 20, bottom: 20, left: 18, right: 18 },
};

/**
 * A repeater body leaf block (heading/text/image/button/divider/spacer only —
 * no nesting). Reuses createBlock then narrows the type.
 */
export function createRepeaterBodyBlock(type: RepeaterBodyBlock['type']): RepeaterBodyBlock {
  return createBlock(type) as RepeaterBodyBlock;
}

export function createSection(layout: SectionLayout = '100'): TemplateSection {
  return {
    id: newDocId('sec'),
    layout,
    background: '#FFFFFF',
    padding: { ...DEFAULT_PADDING },
    columns: SECTION_LAYOUT_COLUMNS[layout].map(() => createColumn()),
  };
}

export function createColumn(): TemplateColumn {
  return { id: newDocId('col'), blocks: [] };
}

/** D4: a new blank template opens with brand header + footer pre-inserted. */
export function createBlankDocument(): TemplateDocument {
  const header = createSection('100');
  header.background = null;
  header.padding = { top: 0, bottom: 0, left: 0, right: 0 };
  header.columns[0].blocks.push(createBlock('brandHeader'));

  const body = createSection('100');

  const footer = createSection('100');
  footer.background = null;
  footer.padding = { top: 0, bottom: 0, left: 0, right: 0 };
  footer.columns[0].blocks.push(createBlock('brandFooter'));

  return { schemaVersion: TEMPLATE_SCHEMA_VERSION, sections: [header, body, footer] };
}

/**
 * A blank DOCUMENT-surface doc (F2 D3): carries `pageSetup` (forever-contract
 * root) + brand header and an empty body section. No social footer (documents
 * print to paper).
 */
export function createBlankDocumentDoc(): TemplateDocument {
  const header = createSection('100');
  header.background = null;
  header.padding = { top: 0, bottom: 0, left: 0, right: 0 };
  header.columns[0].blocks.push(createBlock('brandHeader'));

  const body = createSection('100');

  return {
    schemaVersion: TEMPLATE_SCHEMA_VERSION,
    pageSetup: { ...DEFAULT_PAGE_SETUP, margins: { ...DEFAULT_PAGE_SETUP.margins } },
    sections: [header, body],
  };
}

// ---------------------------------------------------------------------------
// Immutable document operations (the editor's only mutation surface)
// ---------------------------------------------------------------------------

export interface BlockAddress {
  sectionId: string;
  columnId: string;
  blockId: string;
}

function mapSections(
  doc: TemplateDocument,
  fn: (section: TemplateSection) => TemplateSection,
): TemplateDocument {
  return { ...doc, sections: doc.sections.map(fn) };
}

export function findBlock(
  doc: TemplateDocument,
  blockId: string,
): { block: TemplateBlock; address: BlockAddress } | null {
  for (const section of doc.sections) {
    for (const column of section.columns) {
      const block = column.blocks.find((b) => b.id === blockId);
      if (block) {
        return {
          block,
          address: { sectionId: section.id, columnId: column.id, blockId },
        };
      }
    }
  }
  return null;
}

export function findSection(doc: TemplateDocument, sectionId: string): TemplateSection | null {
  return doc.sections.find((s) => s.id === sectionId) ?? null;
}

export function insertBlock(
  doc: TemplateDocument,
  sectionId: string,
  columnId: string,
  block: TemplateBlock,
  index?: number,
): TemplateDocument {
  return mapSections(doc, (section) => {
    if (section.id !== sectionId) return section;
    return {
      ...section,
      columns: section.columns.map((column) => {
        if (column.id !== columnId) return column;
        const blocks = [...column.blocks];
        blocks.splice(index ?? blocks.length, 0, block);
        return { ...column, blocks };
      }),
    };
  });
}

export function removeBlock(doc: TemplateDocument, blockId: string): TemplateDocument {
  return mapSections(doc, (section) => ({
    ...section,
    columns: section.columns.map((column) => ({
      ...column,
      blocks: column.blocks.filter((b) => b.id !== blockId),
    })),
  }));
}

export function updateBlock(
  doc: TemplateDocument,
  blockId: string,
  patch: Partial<TemplateBlock>,
): TemplateDocument {
  return mapSections(doc, (section) => ({
    ...section,
    columns: section.columns.map((column) => ({
      ...column,
      blocks: column.blocks.map((b) =>
        b.id === blockId ? ({ ...b, ...patch } as TemplateBlock) : b,
      ),
    })),
  }));
}

/** Move a block to (sectionId, columnId, index) — drag-and-drop commit. */
export function moveBlock(
  doc: TemplateDocument,
  blockId: string,
  target: { sectionId: string; columnId: string; index: number },
): TemplateDocument {
  const found = findBlock(doc, blockId);
  if (!found) return doc;

  // Compute the index shift when moving within the same column.
  const sameColumn = found.address.columnId === target.columnId;
  const currentIndex = (() => {
    const section = findSection(doc, found.address.sectionId);
    const column = section?.columns.find((c) => c.id === found.address.columnId);
    return column ? column.blocks.findIndex((b) => b.id === blockId) : -1;
  })();

  let insertIndex = target.index;
  if (sameColumn && currentIndex !== -1 && currentIndex < target.index) {
    insertIndex -= 1;
  }

  const without = removeBlock(doc, blockId);
  return insertBlock(without, target.sectionId, target.columnId, found.block, insertIndex);
}

export function insertSection(
  doc: TemplateDocument,
  section: TemplateSection,
  index?: number,
): TemplateDocument {
  const sections = [...doc.sections];
  sections.splice(index ?? sections.length, 0, section);
  return { ...doc, sections };
}

export function removeSection(doc: TemplateDocument, sectionId: string): TemplateDocument {
  return { ...doc, sections: doc.sections.filter((s) => s.id !== sectionId) };
}

export function updateSection(
  doc: TemplateDocument,
  sectionId: string,
  patch: Partial<TemplateSection>,
): TemplateDocument {
  return mapSections(doc, (s) => (s.id === sectionId ? { ...s, ...patch } : s));
}

export function moveSection(doc: TemplateDocument, sectionId: string, toIndex: number): TemplateDocument {
  const from = doc.sections.findIndex((s) => s.id === sectionId);
  if (from === -1) return doc;
  const sections = [...doc.sections];
  const [section] = sections.splice(from, 1);
  sections.splice(toIndex > from ? toIndex - 1 : toIndex, 0, section);
  return { ...doc, sections };
}

/**
 * Change a section's layout, preserving blocks: extra columns' blocks fold
 * into the last remaining column; new columns start empty.
 */
export function changeSectionLayout(
  doc: TemplateDocument,
  sectionId: string,
  layout: SectionLayout,
): TemplateDocument {
  return mapSections(doc, (section) => {
    if (section.id !== sectionId || section.layout === layout) return section;
    const targetCount = SECTION_LAYOUT_COLUMNS[layout].length;
    const columns = [...section.columns];
    while (columns.length > targetCount) {
      const overflow = columns.pop()!;
      const last = columns[columns.length - 1];
      columns[columns.length - 1] = { ...last, blocks: [...last.blocks, ...overflow.blocks] };
    }
    while (columns.length < targetCount) columns.push(createColumn());
    return { ...section, layout, columns };
  });
}

/** Pull `{{ dotted.path }}` tokens out of a string into `out`. */
function collectTokens(value: string | null | undefined, out: Set<string>): void {
  if (!value) return;
  const pattern = /\{\{\s*([\w.]+)\s*\}\}/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(value)) !== null) out.add(match[1]);
}

/** Scalar (non-`row.*`) merge tokens used inside a single leaf block. */
function collectBlockTokens(block: TemplateBlock, out: Set<string>): void {
  switch (block.type) {
    case 'heading':
      collectTokens(block.text, out);
      break;
    case 'text':
      collectTokens(block.html, out);
      break;
    case 'button':
      collectTokens(block.label, out);
      collectTokens(block.href, out);
      break;
    case 'image':
      collectTokens(block.href, out);
      break;
    case 'customHtml':
      collectTokens(block.html, out);
      break;
    case 'qr':
      collectTokens(block.data, out);
      break;
    default:
      break;
  }
}

/**
 * Every CONTEXT merge token used in the doc + subject (required-facts check).
 * `row.*` tokens (table/repeater iterator scope) are deliberately EXCLUDED —
 * they resolve against the source's item facts, not the context vocabulary.
 */
export function collectMergeTokens(doc: TemplateDocument, subject: string): Set<string> {
  const tokens = new Set<string>();
  collectTokens(subject, tokens);
  for (const section of doc.sections) {
    for (const column of section.columns) {
      for (const block of column.blocks) {
        if (block.type === 'table') {
          for (const row of block.footer ?? []) {
            for (const cell of row.cells) collectTokens(cell.text, tokens);
          }
        } else if (block.type === 'repeater') {
          // Repeater body uses row.* (scoped) — only doc-level scalars (rare)
          // count toward required facts.
          for (const child of block.body) collectBlockTokens(child, tokens);
        } else {
          collectBlockTokens(block, tokens);
        }
      }
    }
  }
  // row.* are iterator-scoped, never a context fact.
  for (const t of Array.from(tokens)) if (t.startsWith('row.')) tokens.delete(t);
  return tokens;
}

// ---------------------------------------------------------------------------
// Document-surface validation mirror (F2 D10) — keep PARITY with the backend
// validate_doc document branch (422 `{problems:[...]}`).
// ---------------------------------------------------------------------------

const PAGE_SIZES = new Set<PageSetup['size']>(['A4', 'Letter']);
const PAGE_ORIENTATIONS = new Set<PageSetup['orientation']>(['portrait', 'landscape']);

/** Minimal view of a context the document validator needs. */
export interface DocumentValidationContext {
  /** Scalar fact keys (the context's `facts[].key`). */
  factKeys: Set<string>;
  /** listFact key → its declared item-fact keys. */
  listFacts: Map<string, Set<string>>;
}

/** Build a {@link DocumentValidationContext} from the wire context shape. */
export function documentValidationContext(context: {
  facts: { key: string }[];
  listFacts?: { key: string; itemFacts: { key: string }[] }[];
}): DocumentValidationContext {
  return {
    factKeys: new Set(context.facts.map((f) => f.key)),
    listFacts: new Map(
      (context.listFacts ?? []).map((lf) => [lf.key, new Set(lf.itemFacts.map((f) => f.key))]),
    ),
  };
}

/** Tokens NOT prefixed `row.` (scalar context refs) inside a value. */
function scalarTokens(value: string | null | undefined): string[] {
  const out = new Set<string>();
  collectTokens(value, out);
  return Array.from(out).filter((t) => !t.startsWith('row.'));
}

/** Tokens prefixed `row.` (iterator scope), with the prefix stripped. */
function rowTokens(value: string | null | undefined): string[] {
  const out = new Set<string>();
  collectTokens(value, out);
  return Array.from(out)
    .filter((t) => t.startsWith('row.'))
    .map((t) => t.slice('row.'.length));
}

/**
 * Validate a DOCUMENT-surface doc against its context. Returns a flat list of
 * human-readable problems ([] = valid). Mirrors backend D10:
 *  - page setup (size/orientation/non-negative margins)
 *  - table/repeater source must be a known list fact
 *  - row.<k> must be a known item fact of the bound source
 *  - row.* used OUTSIDE a table/repeater body (row-scope leak)
 *  - scalar token referencing an unknown context fact
 *  - empty table columns / empty repeater body
 */
export function validateDocument(
  doc: TemplateDocument,
  subject: string,
  context: DocumentValidationContext,
): string[] {
  const problems: string[] = [];

  // --- Page setup ---
  const page = doc.pageSetup;
  if (page) {
    if (!PAGE_SIZES.has(page.size)) problems.push(`Unknown page size "${page.size}".`);
    if (!PAGE_ORIENTATIONS.has(page.orientation))
      problems.push(`Unknown page orientation "${page.orientation}".`);
    for (const side of ['top', 'bottom', 'left', 'right'] as const) {
      const m = page.margins[side];
      if (!Number.isFinite(m) || m < 0) problems.push(`Page margin "${side}" must be ≥ 0.`);
    }
  }

  const knownScalar = (token: string) => context.factKeys.has(token);

  // Scalar tokens used outside any iterator body (subject + leaf blocks +
  // footer cells) must resolve against the context; row.* there is a leak.
  const checkScalarValue = (value: string | null | undefined, where: string) => {
    for (const tok of scalarTokens(value)) {
      if (!knownScalar(tok)) problems.push(`Unknown merge field "{{${tok}}}" in ${where}.`);
    }
    if (rowTokens(value).length) problems.push(`"row.*" can only be used inside a table or repeater body (${where}).`);
  };

  checkScalarValue(subject, 'subject');

  const checkLeafBlock = (block: TemplateBlock, where: string) => {
    switch (block.type) {
      case 'heading':
        checkScalarValue(block.text, where);
        break;
      case 'text':
        checkScalarValue(block.html, where);
        break;
      case 'button':
        checkScalarValue(block.label, where);
        checkScalarValue(block.href, where);
        break;
      case 'image':
        checkScalarValue(block.href, where);
        break;
      case 'customHtml':
        checkScalarValue(block.html, where);
        break;
      case 'qr':
        checkScalarValue(block.data, where);
        break;
      default:
        break;
    }
  };

  for (const section of doc.sections) {
    for (const column of section.columns) {
      for (const block of column.blocks) {
        if (block.type === 'table') {
          const items = context.listFacts.get(block.source);
          if (!block.source) problems.push('A table block has no source list selected.');
          else if (!items) problems.push(`Table source "${block.source}" is not a known list field.`);
          if (block.columns.length === 0) problems.push('A table block has no columns.');
          for (const col of block.columns) {
            if (!col.key) problems.push('A table column has no field bound.');
            else if (items && !items.has(col.key))
              problems.push(`Table column "${col.key}" is not a field of "${block.source}".`);
          }
          // Footer cells bind SCALAR facts only.
          for (const row of block.footer ?? []) {
            for (const cell of row.cells) checkScalarValue(cell.text, 'a table footer cell');
          }
        } else if (block.type === 'repeater') {
          const items = context.listFacts.get(block.source);
          if (!block.source) problems.push('A repeater block has no source list selected.');
          else if (!items) problems.push(`Repeater source "${block.source}" is not a known list field.`);
          if (block.body.length === 0) problems.push('A repeater block has an empty body.');
          for (const child of block.body) {
            // Inside a repeater body: scalar tokens must be context facts; row.*
            // must be an item fact of the bound source.
            const values = bodyBlockValues(child);
            for (const v of values) {
              for (const tok of scalarTokens(v)) {
                if (!knownScalar(tok))
                  problems.push(`Unknown merge field "{{${tok}}}" in a repeater body.`);
              }
              for (const rk of rowTokens(v)) {
                if (items && !items.has(rk))
                  problems.push(`"row.${rk}" is not a field of "${block.source}".`);
              }
            }
          }
        } else {
          checkLeafBlock(block, 'a block');
        }
      }
    }
  }

  return problems;
}

/** All merge-bearing string values of a leaf (repeater-body) block. */
function bodyBlockValues(block: TemplateBlock): (string | null | undefined)[] {
  switch (block.type) {
    case 'heading':
      return [block.text];
    case 'text':
      return [block.html];
    case 'button':
      return [block.label, block.href];
    case 'image':
      return [block.href];
    case 'customHtml':
      return [block.html];
    case 'qr':
      return [block.data];
    default:
      return [];
  }
}
