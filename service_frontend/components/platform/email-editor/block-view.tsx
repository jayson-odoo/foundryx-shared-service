'use client';

import { useEffect, useRef } from 'react';
import { Filter, QrCode } from 'lucide-react';
import { sanitizeHtml } from '@/lib/sanitize-html';
import type { BrandRenderValues } from '@/lib/template-render';
import type {
  RepeaterBlock,
  TableBlock,
  TemplateBlock,
  TemplateListFact,
} from '@/types/templates';

/**
 * Canvas-side visual rendering of a block (WYSIWYG approximation; the real
 * output is the backend MJML pipeline). Heading/Text support inline
 * on-canvas editing (D12) - commit on blur.
 */

export interface BlockViewProps {
  block: TemplateBlock;
  editing: boolean;
  brand: BrandRenderValues;
  /** List facts (document surface) - sample rows for table/repeater previews. */
  listFacts?: TemplateListFact[];
  onInlineChange?: (patch: Partial<TemplateBlock>) => void;
}

/** One sample row {itemKey: sample} from a list fact (the source's item samples). */
function sampleRow(source: string, listFacts: TemplateListFact[]): Record<string, string> {
  const lf = listFacts.find((f) => f.key === source);
  if (!lf) return {};
  return Object.fromEntries(lf.itemFacts.map((f) => [f.key, f.sample]));
}

/** Substitute {{ scoped.path }} tokens against a flat fact map (preview only). */
function renderTokens(value: string, facts: Record<string, string>): string {
  return value.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (_, key: string) =>
    key in facts ? facts[key] : `⟦${key}?⟧`,
  );
}

/** contentEditable wrapper that re-syncs only when external value changes. */
function InlineEditable({
  html,
  plainText = false,
  className,
  style,
  disabled,
  onCommit,
  testId,
}: {
  html: string;
  plainText?: boolean;
  className?: string;
  style?: React.CSSProperties;
  disabled: boolean;
  onCommit: (value: string) => void;
  testId: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const current = plainText ? el.textContent ?? '' : el.innerHTML;
    if (current !== html && document.activeElement !== el) {
      if (plainText) el.textContent = html;
      else el.innerHTML = html;
    }
  }, [html, plainText]);

  return (
    // NO dangerouslySetInnerHTML and NO children - React must never manage
    // this element's content. With dSIH, any parent rerender (DndContext
    // init, click-select) re-applied the stale value and WIPED the user's
    // typing before blur could commit it (the "text resets / nothing saves"
    // bug). The sync effect above is the single writer.
    <div
      ref={ref}
      data-testid={testId}
      contentEditable={!disabled}
      suppressContentEditableWarning
      className={`outline-none ${disabled ? '' : 'cursor-text rounded-sm focus:ring-1 focus:ring-primary/60'} ${className ?? ''}`}
      style={style}
      onBlur={() => {
        const el = ref.current;
        if (!el) return;
        onCommit(plainText ? el.textContent ?? '' : el.innerHTML);
      }}
      // Single-line plain text: keep Enter from inserting divs.
      onKeyDown={
        plainText
          ? (e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                (e.target as HTMLElement).blur();
              }
            }
          : undefined
      }
    />
  );
}

const HEADING_SIZES = { 1: 'text-2xl', 2: 'text-xl', 3: 'text-base' } as const;

export function BlockView({ block, editing, brand, listFacts = [], onInlineChange }: BlockViewProps) {
  switch (block.type) {
    case 'table':
      return <TablePreview block={block} listFacts={listFacts} />;
    case 'repeater':
      return <RepeaterPreview block={block} brand={brand} listFacts={listFacts} />;
    case 'heading':
      return (
        <InlineEditable
          html={block.text}
          plainText
          disabled={!editing}
          testId={`block-heading-${block.id}`}
          className={`font-heading font-bold ${HEADING_SIZES[block.level]}`}
          style={{ textAlign: block.align }}
          onCommit={(text) => onInlineChange?.({ text })}
        />
      );
    case 'text':
      // Rendered display (not inline-editable): rich text is edited in the
      // panel's WYSIWYG field - inline contentEditable let users type raw
      // tags that serialized to escaped `&lt;i&gt;`.
      return (
        <div
          data-testid={`block-text-${block.id}`}
          className="text-sm leading-relaxed [&_a]:text-primary [&_a]:underline [&_ol]:list-decimal [&_ol]:ps-5 [&_ul]:list-disc [&_ul]:ps-5"
          style={{ textAlign: block.align }}
          dangerouslySetInnerHTML={{
            __html: block.html
              ? sanitizeHtml(block.html)
              : '<span class="text-muted-foreground">Empty text - edit in the panel</span>',
          }}
        />
      );
    case 'image': {
      const src = block.src;
      if (!src) {
        return (
          <div className="flex items-center justify-center bg-muted px-4 py-8 text-xs text-muted-foreground">
            Image - set a source in the panel
          </div>
        );
      }
      return (
        <img
          src={src}
          alt={block.alt}
          className="max-w-full"
          style={{
            width: block.width ? `${block.width}px` : undefined,
            marginInline: block.align === 'center' ? 'auto' : undefined,
            display: 'block',
          }}
        />
      );
    }
    case 'button':
      return (
        <div style={{ textAlign: block.align }}>
          <span
            className="inline-block px-5 py-2.5 text-sm font-semibold"
            style={{
              backgroundColor: block.backgroundColor ?? brand.primaryColor,
              color: block.textColor ?? '#FFFFFF',
              borderRadius: `${block.borderRadius}px`,
            }}
          >
            {block.label || 'Button'}
          </span>
        </div>
      );
    case 'divider':
      return (
        <hr
          className="border-0"
          style={{ borderTop: `${block.thickness}px solid ${block.color}` }}
        />
      );
    case 'spacer':
      return (
        <div
          className="rounded-sm bg-[repeating-linear-gradient(45deg,transparent,transparent_6px,var(--muted)_6px,var(--muted)_7px)]"
          style={{ height: `${block.height}px` }}
        />
      );
    case 'socialLinks': {
      const links = block.links ?? brand.socials;
      return (
        <div className="flex flex-wrap gap-2 text-xs text-muted-foreground" style={{ justifyContent: block.align === 'center' ? 'center' : block.align === 'right' ? 'flex-end' : 'flex-start' }}>
          {links.length ? (
            links.map((l) => (
              <span key={l.platform} className="rounded-full border border-input px-2 py-0.5">
                {l.platform}
              </span>
            ))
          ) : (
            <span>Social links - none set in branding yet</span>
          )}
        </div>
      );
    }
    case 'brandHeader': {
      const bg = block.overrides?.backgroundColor ?? brand.primaryColor;
      const logo = block.overrides?.logoSrc ?? brand.logoSrc;
      return (
        <div className="flex items-center px-6 py-4" style={{ backgroundColor: bg }}>
          {logo ? (
            <img src={logo} alt={brand.tenantName} className="h-9" />
          ) : (
            <span className="font-heading text-lg font-bold text-white">{brand.tenantName}</span>
          )}
        </div>
      );
    }
    case 'brandFooter': {
      const bg = block.overrides?.backgroundColor ?? '#18181B';
      const text = block.overrides?.footerText ?? brand.footerText;
      const showSocials = block.overrides?.showSocials ?? true;
      return (
        <div className="px-6 py-5 text-center" style={{ backgroundColor: bg }}>
          <p className="text-xs text-zinc-400">{text || 'Footer text - set it in Branding settings'}</p>
          {showSocials && brand.socials.length > 0 && (
            <div className="mt-2 flex justify-center gap-2 text-[11px] text-zinc-500">
              {brand.socials.map((l) => (
                <span key={l.platform}>{l.platform}</span>
              ))}
            </div>
          )}
        </div>
      );
    }
    case 'customHtml':
      return (
        <pre className="overflow-x-auto rounded-md bg-muted px-3 py-2 font-mono text-xs text-muted-foreground">
          {block.html || '<!-- custom HTML - edit in the panel -->'}
        </pre>
      );
    case 'qr': {
      const justify =
        block.align === 'left' ? 'flex-start' : block.align === 'right' ? 'flex-end' : 'center';
      return (
        <div className="flex py-2" style={{ justifyContent: justify }}>
          <div
            className="flex flex-col items-center justify-center gap-1 rounded border border-dashed border-input bg-muted text-[10px] text-muted-foreground"
            style={{ width: block.size, height: block.size }}
          >
            <QrCode className="size-5" />
            <span className="max-w-full break-all px-1 text-center">{block.data || 'QR data'}</span>
          </div>
        </div>
      );
    }
  }
}

/**
 * Table preview (F2 D4): header from columns, ONE sample body row from the
 * bound source's item samples, footer cells. Read-only WYSIWYG approximation -
 * the backend repeats the body per real list item across page breaks.
 */
function TablePreview({ block, listFacts }: { block: TableBlock; listFacts: TemplateListFact[] }) {
  const row = sampleRow(block.source, listFacts);
  const cols = block.columns;
  return (
    <div data-testid={`block-table-${block.id}`} className="overflow-x-auto">
      {!block.source && (
        <p className="px-1 pb-1 text-xs text-muted-foreground">No source list bound yet.</p>
      )}
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b-2 border-foreground/40">
            {cols.length ? (
              cols.map((c, i) => (
                <th key={i} className="px-2 py-1 font-semibold" style={{ textAlign: c.align }}>
                  {c.header || c.key || '-'}
                </th>
              ))
            ) : (
              <th className="px-2 py-1 text-left text-muted-foreground">No columns</th>
            )}
          </tr>
        </thead>
        <tbody>
          <tr className="border-b border-input">
            {cols.length ? (
              cols.map((c, i) => (
                <td key={i} className="px-2 py-1" style={{ textAlign: c.align }}>
                  {c.key ? (row[c.key] ?? `⟦row.${c.key}?⟧`) : '-'}
                </td>
              ))
            ) : (
              <td className="px-2 py-1 text-muted-foreground">-</td>
            )}
          </tr>
        </tbody>
        {block.footer && block.footer.length > 0 && (
          <tfoot>
            {block.footer.map((fRow, ri) => (
              <tr key={ri} className="border-t border-input">
                {fRow.cells.map((cell, ci) => (
                  <td
                    key={ci}
                    colSpan={cell.span}
                    className="px-2 py-1 font-medium"
                    style={{ textAlign: cell.align }}
                  >
                    {renderTokens(cell.text, {})}
                  </td>
                ))}
              </tr>
            ))}
          </tfoot>
        )}
      </table>
    </div>
  );
}

/**
 * Repeater preview (F2 D5): renders the body ONCE against the source's sample
 * row-0 (`row.<key>` resolved from item samples). The backend stamps the body
 * per real list item.
 */
function RepeaterPreview({
  block,
  brand,
  listFacts,
}: {
  block: RepeaterBlock;
  brand: BrandRenderValues;
  listFacts: TemplateListFact[];
}) {
  const row = sampleRow(block.source, listFacts);
  const rowFacts: Record<string, string> = Object.fromEntries(
    Object.entries(row).map(([k, v]) => [`row.${k}`, v]),
  );
  return (
    <div
      data-testid={`block-repeater-${block.id}`}
      className="rounded-md border border-dashed border-input p-2"
    >
      {!block.source && (
        <p className="pb-1 text-xs text-muted-foreground">No source list bound yet.</p>
      )}
      {block.body.length === 0 ? (
        <p className="px-1 py-2 text-xs text-muted-foreground">Empty repeater body.</p>
      ) : (
        <div className="flex flex-col gap-1">
          {block.body.map((child) => (
            <BlockView
              key={child.id}
              block={resolveRowTokens(child, rowFacts)}
              editing={false}
              brand={brand}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** Apply sample row.* values into a leaf block's text fields (preview only). */
function resolveRowTokens(block: TemplateBlock, rowFacts: Record<string, string>): TemplateBlock {
  switch (block.type) {
    case 'heading':
      return { ...block, text: renderTokens(block.text, rowFacts) };
    case 'text':
      return { ...block, html: renderTokens(block.html, rowFacts) };
    case 'button':
      return {
        ...block,
        label: renderTokens(block.label, rowFacts),
        href: renderTokens(block.href, rowFacts),
      };
    default:
      return block;
  }
}

/** Amber chip shown on conditioned blocks (visibility rules - D8). */
export function ConditionIndicator({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return (
    <span
      data-testid="condition-indicator"
      className="absolute -top-2 end-6 z-10 inline-flex items-center gap-1 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700"
    >
      <Filter className="size-2.5" />
      Conditional
    </span>
  );
}
