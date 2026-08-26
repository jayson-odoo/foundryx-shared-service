'use client';

import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { RuleBuilder } from '@/components/platform/rule-builder';
import { SearchSelect } from '@/components/platform/search-select';
import { createRepeaterBodyBlock } from '@/lib/template-doc';
import type { RuleFact, RuleGroup } from '@/types/rules';
import type {
  RepeaterBlock,
  RepeaterBodyBlock,
  SectionLayout,
  TableBlock,
  TableColumn,
  TableFooterRow,
  TemplateBlock,
  TemplateContextFact,
  TemplateListFact,
  TemplateSection,
  TextAlign,
} from '@/types/templates';
import { MergeInput } from './merge-input';
import { RichTextField } from './rich-text-field';

const ALIGN_OPTIONS = [
  { label: 'Left', value: 'left' },
  { label: 'Center', value: 'center' },
  { label: 'Right', value: 'right' },
];

const LAYOUT_OPTIONS: { label: string; value: SectionLayout }[] = [
  { label: '1 column', value: '100' },
  { label: '2 columns (50 / 50)', value: '50/50' },
  { label: '3 columns (33 / 33 / 33)', value: '33/33/33' },
  { label: '2 columns (67 / 33)', value: '67/33' },
];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function ColorField({
  label,
  value,
  onChange,
  allowEmpty,
  emptyHint,
}: {
  label: string;
  value: string | null;
  onChange: (value: string | null) => void;
  allowEmpty?: boolean;
  emptyHint?: string;
}) {
  return (
    <Field label={label}>
      <div className="flex items-center gap-2">
        <input
          type="color"
          aria-label={label}
          className="size-8 cursor-pointer rounded border border-input bg-background"
          value={value ?? '#FFFFFF'}
          onChange={(e) => onChange(e.target.value)}
        />
        {allowEmpty && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-xs"
            disabled={value === null}
            onClick={() => onChange(null)}
          >
            {emptyHint ?? 'Use brand default'}
          </Button>
        )}
      </div>
    </Field>
  );
}

function AlignField({ value, onChange }: { value: TextAlign; onChange: (v: TextAlign) => void }) {
  return (
    <Field label="Alignment">
      <SearchSelect
        options={ALIGN_OPTIONS}
        value={value}
        onChange={(v) => onChange(v as TextAlign)}
        ariaLabel="Alignment"
      />
    </Field>
  );
}

function NumberField({
  label,
  value,
  onChange,
  min = 0,
  max = 999,
  nullable,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  min?: number;
  max?: number;
  nullable?: boolean;
}) {
  return (
    <Field label={label}>
      <Input
        type="number"
        min={min}
        max={max}
        aria-label={label}
        value={value ?? ''}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === '' && nullable) return onChange(null);
          const parsed = Number(raw);
          if (!Number.isNaN(parsed)) onChange(parsed);
        }}
      />
    </Field>
  );
}

// ---------------------------------------------------------------------------

export interface SettingsPanelProps {
  selection:
    | { kind: 'block'; block: TemplateBlock }
    | { kind: 'section'; section: TemplateSection }
    | null;
  mergeFields: TemplateContextFact[];
  visibilityFacts: RuleFact[];
  /** Content-only mode - hide structure controls (remove block, section layout). */
  structureLocked?: boolean;
  /** List facts (document surface) - back the table/repeater source pickers. */
  listFacts?: TemplateListFact[];
  onBlockChange: (blockId: string, patch: Partial<TemplateBlock>) => void;
  onSectionChange: (sectionId: string, patch: Partial<TemplateSection>) => void;
  onSectionLayoutChange: (sectionId: string, layout: SectionLayout) => void;
  onRemoveBlock: (blockId: string) => void;
}

export function SettingsPanel({
  selection,
  mergeFields,
  visibilityFacts,
  structureLocked = false,
  listFacts = [],
  onBlockChange,
  onSectionChange,
  onSectionLayoutChange,
  onRemoveBlock,
}: SettingsPanelProps) {
  if (!selection) {
    return (
      <div data-testid="settings-panel-empty" className="px-1 py-8 text-center text-xs text-muted-foreground">
        {structureLocked
          ? 'Select a block to edit its wording.'
          : 'Select a block or section in the canvas to edit its settings.'}
      </div>
    );
  }

  // Sections are structure - nothing to edit in content-only mode.
  if (selection.kind === 'section' && structureLocked) {
    return (
      <div className="px-1 py-8 text-center text-xs text-muted-foreground">
        Select a block to edit its wording. Layout changes live in Templates.
      </div>
    );
  }

  if (selection.kind === 'section') {
    const section = selection.section;
    const patch = (p: Partial<TemplateSection>) => onSectionChange(section.id, p);
    return (
      <div data-testid="settings-panel-section" className="flex flex-col gap-4">
        <span className="text-sm font-semibold">Section</span>
        <Field label="Layout">
          <SearchSelect
            options={LAYOUT_OPTIONS}
            value={section.layout}
            onChange={(v) => onSectionLayoutChange(section.id, v as SectionLayout)}
            ariaLabel="Section layout"
          />
        </Field>
        <ColorField
          label="Background"
          value={section.background}
          onChange={(background) => patch({ background })}
          allowEmpty
          emptyHint="Transparent"
        />
        <div className="grid grid-cols-2 gap-2">
          <NumberField label="Padding top" value={section.padding.top} onChange={(v) => patch({ padding: { ...section.padding, top: v ?? 0 } })} />
          <NumberField label="Padding bottom" value={section.padding.bottom} onChange={(v) => patch({ padding: { ...section.padding, bottom: v ?? 0 } })} />
          <NumberField label="Padding left" value={section.padding.left} onChange={(v) => patch({ padding: { ...section.padding, left: v ?? 0 } })} />
          <NumberField label="Padding right" value={section.padding.right} onChange={(v) => patch({ padding: { ...section.padding, right: v ?? 0 } })} />
        </div>
        <VisibilitySection
          conditions={section.conditionsJson ?? null}
          facts={visibilityFacts}
          remountKey={section.id}
          onChange={(conditionsJson) => patch({ conditionsJson })}
        />
      </div>
    );
  }

  const block = selection.block;
  const patch = (p: Partial<TemplateBlock>) => onBlockChange(block.id, p);

  return (
    <div data-testid={`settings-panel-${block.type}`} className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold capitalize">{labelFor(block.type)}</span>
        {!structureLocked && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-destructive"
            data-testid="remove-block"
            onClick={() => onRemoveBlock(block.id)}
          >
            <Trash2 className="size-3.5" /> Remove
          </Button>
        )}
      </div>

      {block.type === 'heading' && (
        <>
          <Field label="Text">
            <MergeInput value={block.text} onChange={(text) => patch({ text })} fields={mergeFields} aria-label="Heading text" />
          </Field>
          <Field label="Level">
            <SearchSelect
              options={[
                { label: 'H1', value: '1' },
                { label: 'H2', value: '2' },
                { label: 'H3', value: '3' },
              ]}
              value={String(block.level)}
              onChange={(v) => patch({ level: Number(v) as 1 | 2 | 3 })}
              ariaLabel="Heading level"
            />
          </Field>
          <AlignField value={block.align} onChange={(align) => patch({ align })} />
        </>
      )}

      {block.type === 'text' && (
        <>
          <Field label="Text">
            <RichTextField
              value={block.html}
              onChange={(html) => patch({ html })}
              fields={mergeFields}
              aria-label="Text content"
            />
          </Field>
          <AlignField value={block.align} onChange={(align) => patch({ align })} />
        </>
      )}

      {block.type === 'image' && (
        <>
          <Field label="Image URL">
            <Input
              aria-label="Image URL"
              value={block.src ?? ''}
              placeholder="https://…"
              onChange={(e) => patch({ src: e.target.value || null })}
            />
          </Field>
          <Field label="Alt text">
            <Input aria-label="Alt text" value={block.alt} onChange={(e) => patch({ alt: e.target.value })} />
          </Field>
          <NumberField label="Width (px, empty = natural)" value={block.width} onChange={(width) => patch({ width })} nullable max={600} />
          <Field label="Link (optional)">
            <MergeInput value={block.href ?? ''} onChange={(href) => patch({ href: href || null })} fields={mergeFields} aria-label="Image link" />
          </Field>
          <AlignField value={block.align} onChange={(align) => patch({ align })} />
        </>
      )}

      {block.type === 'button' && (
        <>
          <Field label="Label">
            <MergeInput value={block.label} onChange={(label) => patch({ label })} fields={mergeFields} aria-label="Button label" />
          </Field>
          <Field label="Link">
            <MergeInput value={block.href} onChange={(href) => patch({ href })} fields={mergeFields} aria-label="Button link" />
          </Field>
          <ColorField label="Background" value={block.backgroundColor} onChange={(backgroundColor) => patch({ backgroundColor })} allowEmpty />
          <ColorField label="Text color" value={block.textColor} onChange={(textColor) => patch({ textColor })} allowEmpty emptyHint="White" />
          <NumberField label="Corner radius" value={block.borderRadius} onChange={(v) => patch({ borderRadius: v ?? 0 })} max={32} />
          <AlignField value={block.align} onChange={(align) => patch({ align })} />
        </>
      )}

      {block.type === 'divider' && (
        <>
          <ColorField label="Color" value={block.color} onChange={(color) => patch({ color: color ?? '#E4E4E7' })} />
          <NumberField label="Thickness" value={block.thickness} onChange={(v) => patch({ thickness: v ?? 1 })} min={1} max={8} />
        </>
      )}

      {block.type === 'spacer' && (
        <NumberField label="Height (px)" value={block.height} onChange={(v) => patch({ height: v ?? 8 })} min={4} max={160} />
      )}

      {block.type === 'socialLinks' && (
        <>
          <p className="text-xs text-muted-foreground">
            By default this renders every social URL set in Branding settings. (Per-block overrides arrive with the saved-blocks library.)
          </p>
          <NumberField label="Icon size" value={block.iconSize} onChange={(v) => patch({ iconSize: v ?? 24 })} min={16} max={48} />
          <AlignField value={block.align} onChange={(align) => patch({ align })} />
        </>
      )}

      {block.type === 'brandHeader' && (
        <>
          <p className="text-xs text-muted-foreground">Logo and color follow Branding settings unless overridden here.</p>
          <Field label="Logo override (URL, empty = brand logo)">
            <Input
              aria-label="Logo override"
              placeholder="https://…"
              value={block.overrides?.logoSrc ?? ''}
              onChange={(e) =>
                patch({ overrides: { ...block.overrides, logoSrc: e.target.value || null } })
              }
            />
          </Field>
          <ColorField
            label="Background override"
            value={block.overrides?.backgroundColor ?? null}
            onChange={(backgroundColor) => patch({ overrides: { ...block.overrides, backgroundColor } })}
            allowEmpty
          />
        </>
      )}

      {block.type === 'brandFooter' && (
        <>
          <Field label="Footer text override">
            <Textarea
              aria-label="Footer text override"
              rows={2}
              placeholder="Empty = Branding settings text"
              value={block.overrides?.footerText ?? ''}
              onChange={(e) => patch({ overrides: { ...block.overrides, footerText: e.target.value || null } })}
            />
          </Field>
          <div className="flex items-center justify-between">
            <Label className="text-xs text-muted-foreground">Show social links</Label>
            <Switch
              checked={block.overrides?.showSocials ?? true}
              onCheckedChange={(showSocials) => patch({ overrides: { ...block.overrides, showSocials } })}
              aria-label="Show social links"
            />
          </div>
        </>
      )}

      {block.type === 'customHtml' && (
        <Field label="HTML (sanitized at save)">
          <Textarea
            aria-label="Custom HTML"
            rows={8}
            className="font-mono text-xs"
            value={block.html}
            onChange={(e) => patch({ html: e.target.value })}
          />
        </Field>
      )}

      {block.type === 'qr' && (
        <>
          <Field label="QR data">
            <MergeInput
              value={block.data}
              onChange={(data) => patch({ data })}
              fields={mergeFields}
              aria-label="QR data"
              placeholder="{{ticketLink}}"
            />
          </Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Size (px)">
              <Input
                type="number"
                aria-label="QR size"
                value={block.size}
                onChange={(e) => patch({ size: Number(e.target.value) || 120 })}
              />
            </Field>
            <Field label="Error correction">
              <SearchSelect
                value={block.ecLevel}
                onChange={(v) => patch({ ecLevel: v as typeof block.ecLevel })}
                options={[
                  { label: 'Low (L)', value: 'L' },
                  { label: 'Medium (M)', value: 'M' },
                  { label: 'Quartile (Q)', value: 'Q' },
                  { label: 'High (H)', value: 'H' },
                ]}
                ariaLabel="QR error correction"
              />
            </Field>
          </div>
          <Field label="Align">
            <AlignField value={block.align} onChange={(align) => patch({ align })} />
          </Field>
        </>
      )}

      {block.type === 'table' && (
        <TableEditor
          block={block}
          listFacts={listFacts}
          mergeFields={mergeFields}
          onChange={(p) => patch(p)}
        />
      )}

      {block.type === 'repeater' && (
        <RepeaterEditor
          block={block}
          listFacts={listFacts}
          mergeFields={mergeFields}
          onChange={(p) => patch(p)}
        />
      )}

      <VisibilitySection
        conditions={block.conditionsJson ?? null}
        facts={visibilityFacts}
        remountKey={block.id}
        onChange={(conditionsJson) => patch({ conditionsJson })}
      />
    </div>
  );
}

function labelFor(type: TemplateBlock['type']): string {
  const labels: Record<TemplateBlock['type'], string> = {
    heading: 'Heading',
    text: 'Text',
    image: 'Image',
    button: 'Button',
    divider: 'Divider',
    spacer: 'Spacer',
    socialLinks: 'Social links',
    brandHeader: 'Brand header',
    brandFooter: 'Brand footer',
    customHtml: 'Custom HTML',
    qr: 'QR code',
    table: 'Table',
    repeater: 'Repeater',
  };
  return labels[type];
}

// ---------------------------------------------------------------------------
// Table editor (F2 D4) - source · columns · footer rows.
// ---------------------------------------------------------------------------

/** Item-fact options for the bound source (column-key picker). */
function itemFactOptions(source: string, listFacts: TemplateListFact[]) {
  const lf = listFacts.find((f) => f.key === source);
  return (lf?.itemFacts ?? []).map((f) => ({ label: f.label, value: f.key }));
}

function sourceOptions(listFacts: TemplateListFact[]) {
  return listFacts.map((f) => ({ label: f.label, value: f.key }));
}

function TableEditor({
  block,
  listFacts,
  mergeFields,
  onChange,
}: {
  block: TableBlock;
  listFacts: TemplateListFact[];
  mergeFields: TemplateContextFact[];
  onChange: (patch: Partial<TableBlock>) => void;
}) {
  const colOpts = itemFactOptions(block.source, listFacts);

  const setColumn = (i: number, p: Partial<TableColumn>) =>
    onChange({ columns: block.columns.map((c, idx) => (idx === i ? { ...c, ...p } : c)) });

  const moveColumn = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= block.columns.length) return;
    const cols = [...block.columns];
    [cols[i], cols[j]] = [cols[j], cols[i]];
    onChange({ columns: cols });
  };

  const addColumn = () =>
    onChange({ columns: [...block.columns, { key: '', header: 'Column', align: 'left', width: null }] });

  const removeColumn = (i: number) =>
    onChange({ columns: block.columns.filter((_, idx) => idx !== i) });

  const setFooter = (rows: TableFooterRow[]) => onChange({ footer: rows.length ? rows : null });

  return (
    <div className="flex flex-col gap-3" data-testid="table-editor">
      <Field label="Source list">
        <SearchSelect
          options={sourceOptions(listFacts)}
          value={block.source || null}
          onChange={(v) => onChange({ source: v })}
          ariaLabel="Table source"
          placeholder="Select a list field…"
          emptyText="No list fields in this context."
        />
      </Field>

      <Separator />
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Columns
        </span>
        <Button type="button" variant="ghost" size="sm" data-testid="add-table-column" onClick={addColumn}>
          <Plus className="size-3.5" /> Add
        </Button>
      </div>

      {block.columns.map((col, i) => (
        <div key={i} className="flex flex-col gap-2 rounded-md border border-input p-2" data-testid={`table-column-${i}`}>
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">Column {i + 1}</span>
            <div className="flex items-center">
              <Button type="button" variant="ghost" size="icon" className="size-6" aria-label={`Move column ${i + 1} up`} disabled={i === 0} onClick={() => moveColumn(i, -1)}>
                <ArrowUp className="size-3.5" />
              </Button>
              <Button type="button" variant="ghost" size="icon" className="size-6" aria-label={`Move column ${i + 1} down`} disabled={i === block.columns.length - 1} onClick={() => moveColumn(i, 1)}>
                <ArrowDown className="size-3.5" />
              </Button>
              <Button type="button" variant="ghost" size="icon" className="size-6 text-destructive" aria-label={`Remove column ${i + 1}`} data-testid={`remove-table-column-${i}`} onClick={() => removeColumn(i)}>
                <Trash2 className="size-3.5" />
              </Button>
            </div>
          </div>
          <Field label="Field">
            <SearchSelect
              options={colOpts}
              value={col.key || null}
              onChange={(v) => setColumn(i, { key: v })}
              ariaLabel={`Column ${i + 1} field`}
              placeholder={block.source ? 'Select a field…' : 'Pick a source first'}
              disabled={!block.source}
            />
          </Field>
          <Field label="Header">
            <Input aria-label={`Column ${i + 1} header`} value={col.header} onChange={(e) => setColumn(i, { header: e.target.value })} />
          </Field>
          <Field label="Alignment">
            <SearchSelect options={ALIGN_OPTIONS} value={col.align} onChange={(v) => setColumn(i, { align: v as TextAlign })} ariaLabel={`Column ${i + 1} alignment`} />
          </Field>
        </div>
      ))}

      <Separator />
      <TableFooterEditor footer={block.footer ?? []} mergeFields={mergeFields} onChange={setFooter} />
    </div>
  );
}

function TableFooterEditor({
  footer,
  mergeFields,
  onChange,
}: {
  footer: TableFooterRow[];
  mergeFields: TemplateContextFact[];
  onChange: (rows: TableFooterRow[]) => void;
}) {
  const addRow = () => onChange([...footer, { cells: [{ text: '', align: 'right', span: 1 }] }]);
  const removeRow = (ri: number) => onChange(footer.filter((_, i) => i !== ri));
  const setCell = (ri: number, ci: number, p: Partial<TableFooterRow['cells'][number]>) =>
    onChange(
      footer.map((row, i) =>
        i === ri ? { cells: row.cells.map((c, j) => (j === ci ? { ...c, ...p } : c)) } : row,
      ),
    );
  const addCell = (ri: number) =>
    onChange(
      footer.map((row, i) =>
        i === ri ? { cells: [...row.cells, { text: '', align: 'right', span: 1 }] } : row,
      ),
    );
  const removeCell = (ri: number, ci: number) =>
    onChange(footer.map((row, i) => (i === ri ? { cells: row.cells.filter((_, j) => j !== ci) } : row)));

  return (
    <div className="flex flex-col gap-2" data-testid="table-footer-editor">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Footer rows
        </span>
        <Button type="button" variant="ghost" size="sm" data-testid="add-footer-row" onClick={addRow}>
          <Plus className="size-3.5" /> Add row
        </Button>
      </div>
      {footer.map((row, ri) => (
        <div key={ri} className="flex flex-col gap-2 rounded-md border border-input p-2" data-testid={`footer-row-${ri}`}>
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">Row {ri + 1}</span>
            <div className="flex items-center">
              <Button type="button" variant="ghost" size="sm" onClick={() => addCell(ri)}>
                <Plus className="size-3.5" /> Cell
              </Button>
              <Button type="button" variant="ghost" size="icon" className="size-6 text-destructive" aria-label={`Remove footer row ${ri + 1}`} onClick={() => removeRow(ri)}>
                <Trash2 className="size-3.5" />
              </Button>
            </div>
          </div>
          {row.cells.map((cell, ci) => (
            <div key={ci} className="flex flex-col gap-1.5 rounded border border-input/60 p-1.5">
              <MergeInput value={cell.text} onChange={(text) => setCell(ri, ci, { text })} fields={mergeFields} aria-label={`Footer row ${ri + 1} cell ${ci + 1}`} />
              <div className="grid grid-cols-2 gap-2">
                <NumberField label="Span" value={cell.span} onChange={(v) => setCell(ri, ci, { span: Math.max(1, v ?? 1) })} min={1} max={12} />
                <Field label="Align">
                  <SearchSelect options={ALIGN_OPTIONS} value={cell.align} onChange={(v) => setCell(ri, ci, { align: v as TextAlign })} ariaLabel={`Footer row ${ri + 1} cell ${ci + 1} alignment`} />
                </Field>
              </div>
              {row.cells.length > 1 && (
                <Button type="button" variant="ghost" size="sm" className="self-end text-destructive" onClick={() => removeCell(ri, ci)}>
                  Remove cell
                </Button>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Repeater editor (F2 D5) - source · body (mini block list, row.* picker).
// ---------------------------------------------------------------------------

const REPEATER_BODY_TYPES: { label: string; value: RepeaterBodyBlock['type'] }[] = [
  { label: 'Heading', value: 'heading' },
  { label: 'Text', value: 'text' },
  { label: 'Image', value: 'image' },
  { label: 'Button', value: 'button' },
  { label: 'Divider', value: 'divider' },
  { label: 'Spacer', value: 'spacer' },
];

function RepeaterEditor({
  block,
  listFacts,
  mergeFields,
  onChange,
}: {
  block: RepeaterBlock;
  listFacts: TemplateListFact[];
  mergeFields: TemplateContextFact[];
  onChange: (patch: Partial<RepeaterBlock>) => void;
}) {
  // The body picker offers context scalars PLUS row.<key> tokens of the source.
  const lf = listFacts.find((f) => f.key === block.source);
  const rowFields: TemplateContextFact[] = (lf?.itemFacts ?? []).map((f) => ({
    key: `row.${f.key}`,
    label: `Row · ${f.label}`,
    sample: f.sample,
  }));
  const bodyFields = [...rowFields, ...mergeFields];

  const setBody = (body: RepeaterBodyBlock[]) => onChange({ body });
  const addBodyBlock = (type: RepeaterBodyBlock['type']) =>
    setBody([...block.body, createRepeaterBodyBlock(type)]);
  const removeBodyBlock = (id: string) => setBody(block.body.filter((b) => b.id !== id));
  const updateBodyBlock = (id: string, p: Partial<RepeaterBodyBlock>) =>
    setBody(block.body.map((b) => (b.id === id ? ({ ...b, ...p } as RepeaterBodyBlock) : b)));
  const moveBodyBlock = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= block.body.length) return;
    const body = [...block.body];
    [body[i], body[j]] = [body[j], body[i]];
    setBody(body);
  };

  return (
    <div className="flex flex-col gap-3" data-testid="repeater-editor">
      <Field label="Source list">
        <SearchSelect
          options={sourceOptions(listFacts)}
          value={block.source || null}
          onChange={(v) => onChange({ source: v })}
          ariaLabel="Repeater source"
          placeholder="Select a list field…"
          emptyText="No list fields in this context."
        />
      </Field>

      <Separator />
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Repeated content
        </span>
        <div className="w-32">
          <SearchSelect
            options={REPEATER_BODY_TYPES}
            value={null}
            onChange={(v) => addBodyBlock(v as RepeaterBodyBlock['type'])}
            ariaLabel="Add repeater block"
            placeholder="Add block…"
          />
        </div>
      </div>

      {block.body.map((child, i) => (
        <div key={child.id} className="flex flex-col gap-2 rounded-md border border-input p-2" data-testid={`repeater-body-${child.id}`}>
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium capitalize text-muted-foreground">{child.type}</span>
            <div className="flex items-center">
              <Button type="button" variant="ghost" size="icon" className="size-6" aria-label={`Move ${child.type} up`} disabled={i === 0} onClick={() => moveBodyBlock(i, -1)}>
                <ArrowUp className="size-3.5" />
              </Button>
              <Button type="button" variant="ghost" size="icon" className="size-6" aria-label={`Move ${child.type} down`} disabled={i === block.body.length - 1} onClick={() => moveBodyBlock(i, 1)}>
                <ArrowDown className="size-3.5" />
              </Button>
              <Button type="button" variant="ghost" size="icon" className="size-6 text-destructive" aria-label={`Remove ${child.type}`} data-testid={`remove-repeater-body-${child.id}`} onClick={() => removeBodyBlock(child.id)}>
                <Trash2 className="size-3.5" />
              </Button>
            </div>
          </div>
          <RepeaterBodyFields block={child} fields={bodyFields} onChange={(p) => updateBodyBlock(child.id, p)} />
        </div>
      ))}
    </div>
  );
}

/** Inline content fields for a repeater body leaf block. */
function RepeaterBodyFields({
  block,
  fields,
  onChange,
}: {
  block: RepeaterBodyBlock;
  fields: TemplateContextFact[];
  onChange: (patch: Partial<RepeaterBodyBlock>) => void;
}) {
  switch (block.type) {
    case 'heading':
      return (
        <Field label="Text">
          <MergeInput value={block.text} onChange={(text) => onChange({ text })} fields={fields} aria-label="Repeater heading text" />
        </Field>
      );
    case 'text':
      return (
        <Field label="Text">
          <MergeInput value={block.html} onChange={(html) => onChange({ html })} fields={fields} multiline aria-label="Repeater text" />
        </Field>
      );
    case 'button':
      return (
        <>
          <Field label="Label">
            <MergeInput value={block.label} onChange={(label) => onChange({ label })} fields={fields} aria-label="Repeater button label" />
          </Field>
          <Field label="Link">
            <MergeInput value={block.href} onChange={(href) => onChange({ href })} fields={fields} aria-label="Repeater button link" />
          </Field>
        </>
      );
    case 'image':
      return (
        <Field label="Image URL">
          <MergeInput value={block.src ?? ''} onChange={(src) => onChange({ src: src || null })} fields={fields} aria-label="Repeater image URL" />
        </Field>
      );
    case 'divider':
      return (
        <NumberField label="Thickness" value={block.thickness} onChange={(v) => onChange({ thickness: v ?? 1 })} min={1} max={8} />
      );
    case 'spacer':
      return (
        <NumberField label="Height (px)" value={block.height} onChange={(v) => onChange({ height: v ?? 8 })} min={4} max={160} />
      );
  }
}

/** Block/section visibility conditions - rule engine (D8). */
function VisibilitySection({
  conditions,
  facts,
  remountKey,
  onChange,
}: {
  conditions: RuleGroup | null;
  facts: RuleFact[];
  remountKey: string;
  onChange: (tree: RuleGroup | null) => void;
}) {
  return (
    <div data-testid="visibility-conditions" className="flex flex-col gap-2">
      <Separator />
      <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Visibility conditions
      </span>
      <p className="text-xs text-muted-foreground">
        Shown to a recipient only while these conditions pass. Empty = always shown.
      </p>
      {/* RuleBuilder is mount-initialized - remount per selected element. */}
      <RuleBuilder key={remountKey} facts={facts} value={conditions} onChange={onChange} />
    </div>
  );
}
