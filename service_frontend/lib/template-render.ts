import { SECTION_LAYOUT_COLUMNS, type TemplateBlock, type TemplateDocument } from '@/types/templates';

/**
 * Client-side approximation renderer — MOCK-PHASE preview + test surface only.
 * The production renderer is the backend pipeline (JSON → MJML → mrml → merge,
 * plan 07 D9); Phase B swaps the preview service to `POST /templates/preview`
 * and this module remains only as the Vitest fixture renderer.
 */

export interface BrandRenderValues {
  logoSrc: string | null;
  tenantName: string;
  primaryColor: string;
  footerText: string;
  socials: { platform: string; href: string }[];
}

export const MOCK_BRAND: BrandRenderValues = {
  logoSrc: null,
  tenantName: 'Acme Events',
  primaryColor: '#FF5A00',
  footerText: 'Acme Events · 1 Example Street · Kuala Lumpur',
  socials: [
    { platform: 'facebook', href: 'https://facebook.com/acme' },
    { platform: 'instagram', href: 'https://instagram.com/acme' },
  ],
};

const ESCAPE_MAP: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (ch) => ESCAPE_MAP[ch]);
}

/**
 * Merge substitution — {{ dotted.path }} only (D5). Values HTML-escaped.
 * Missing facts: '' in send mode, loud token in preview mode.
 */
export function renderMergeTokens(
  value: string,
  facts: Record<string, string>,
  mode: 'send' | 'preview' = 'preview',
): string {
  return value.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (_, key: string) => {
    const fact = facts[key];
    if (fact === undefined) {
      return mode === 'preview' ? `⟦${key}?⟧` : '';
    }
    return escapeHtml(fact);
  });
}

function blockHtml(block: TemplateBlock, facts: Record<string, string>, brand: BrandRenderValues): string {
  switch (block.type) {
    case 'heading': {
      const sizes = { 1: 28, 2: 24, 3: 18 } as const;
      return `<h${block.level} style="margin:0 0 8px;font-size:${sizes[block.level]}px;text-align:${block.align};font-family:Poppins,Arial,sans-serif">${renderMergeTokens(block.text, facts)}</h${block.level}>`;
    }
    case 'text':
      // Rich-lite html passes through; only merge tokens substitute.
      return `<div style="font-size:14px;line-height:1.6;text-align:${block.align}">${renderMergeTokens(block.html, facts)}</div>`;
    case 'image': {
      const src = block.src ?? '';
      if (!src) return `<div style="background:#F4F4F5;color:#A1A1AA;text-align:center;padding:32px;font-size:12px">Image</div>`;
      const img = `<img src="${escapeHtml(src)}" alt="${escapeHtml(block.alt)}" style="max-width:100%;${block.width ? `width:${block.width}px;` : ''}display:block;margin:${block.align === 'center' ? '0 auto' : '0'}" />`;
      return block.href ? `<a href="${renderMergeTokens(block.href, facts)}">${img}</a>` : img;
    }
    case 'button': {
      const bg = block.backgroundColor ?? brand.primaryColor;
      const color = block.textColor ?? '#FFFFFF';
      return `<div style="text-align:${block.align}"><a href="${renderMergeTokens(block.href, facts)}" style="display:inline-block;background:${bg};color:${color};padding:10px 20px;border-radius:${block.borderRadius}px;text-decoration:none;font-weight:600;font-size:14px">${renderMergeTokens(block.label, facts)}</a></div>`;
    }
    case 'divider':
      return `<hr style="border:none;border-top:${block.thickness}px solid ${block.color};margin:8px 0" />`;
    case 'spacer':
      return `<div style="height:${block.height}px"></div>`;
    case 'socialLinks': {
      const links = block.links ?? brand.socials;
      if (!links.length) return '';
      const anchors = links
        .map(
          (l) =>
            `<a href="${escapeHtml(l.href)}" style="margin:0 6px;font-size:12px;color:#71717A;text-decoration:none">${escapeHtml(l.platform)}</a>`,
        )
        .join('');
      return `<div style="text-align:${block.align}">${anchors}</div>`;
    }
    case 'brandHeader': {
      const bg = block.overrides?.backgroundColor ?? brand.primaryColor;
      const logo = block.overrides?.logoSrc ?? brand.logoSrc;
      const inner = logo
        ? `<img src="${escapeHtml(logo)}" alt="${escapeHtml(brand.tenantName)}" style="height:36px" />`
        : `<span style="color:#fff;font-weight:700;font-size:18px;font-family:Poppins,Arial,sans-serif">${escapeHtml(brand.tenantName)}</span>`;
      return `<div style="background:${bg};padding:16px 24px">${inner}</div>`;
    }
    case 'brandFooter': {
      const bg = block.overrides?.backgroundColor ?? '#18181B';
      const text = block.overrides?.footerText ?? brand.footerText;
      const showSocials = block.overrides?.showSocials ?? true;
      const socials = showSocials
        ? `<div style="text-align:center;margin-top:8px">${brand.socials
            .map(
              (l) =>
                `<a href="${escapeHtml(l.href)}" style="margin:0 6px;font-size:11px;color:#A1A1AA;text-decoration:none">${escapeHtml(l.platform)}</a>`,
            )
            .join('')}</div>`
        : '';
      return `<div style="background:${bg};padding:24px;text-align:center"><span style="color:#A1A1AA;font-size:12px">${escapeHtml(text)}</span>${socials}</div>`;
    }
    case 'customHtml':
      return block.html;
    case 'table': {
      // Mock HTML preview renders structure only (the authoritative document
      // render is server-side PDF; sample-data binding lives there).
      const head = block.columns
        .map(
          (c) =>
            `<th style="text-align:${c.align};border-bottom:1px solid #E4E4E7;padding:6px;font-size:12px">${escapeHtml(c.header)}</th>`,
        )
        .join('');
      const foot = (block.footer ?? [])
        .map(
          (row) =>
            `<tr>${row.cells
              .map(
                (cell) =>
                  `<td colspan="${cell.span}" style="text-align:${cell.align};padding:6px;font-size:13px;font-weight:600">${renderMergeTokens(cell.text, facts)}</td>`,
              )
              .join('')}</tr>`,
        )
        .join('');
      return `<table style="width:100%;border-collapse:collapse"><thead><tr>${head}</tr></thead><tfoot>${foot}</tfoot></table>`;
    }
    case 'repeater':
      return block.body.map((b) => blockHtml(b, facts, brand)).join('\n');
    case 'qr': {
      // Mock preview placeholder (real QR is generated server-side).
      const justify =
        block.align === 'left' ? 'flex-start' : block.align === 'right' ? 'flex-end' : 'center';
      return `<div style="display:flex;justify-content:${justify};padding:4px 0"><div style="width:${block.size}px;height:${block.size}px;border:1px dashed #A1A1AA;display:flex;align-items:center;justify-content:center;color:#A1A1AA;font-size:11px;text-align:center">QR</div></div>`;
    }
  }
}

/** Doc → standalone preview HTML (mock pipeline; conditions NOT pruned here). */
export function renderDocumentHtml(
  doc: TemplateDocument,
  facts: Record<string, string>,
  brand: BrandRenderValues = MOCK_BRAND,
): string {
  const sections = doc.sections
    .map((section) => {
      const ratios = SECTION_LAYOUT_COLUMNS[section.layout];
      const columns = section.columns
        .map((column, i) => {
          const blocks = column.blocks.map((b) => blockHtml(b, facts, brand)).join('\n');
          return `<td style="width:${ratios[i]}%;vertical-align:top;padding:4px">${blocks}</td>`;
        })
        .join('');
      const pad = section.padding;
      const bg = section.background ? `background:${section.background};` : '';
      return `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="${bg}"><tr><td style="padding:${pad.top}px ${pad.right}px ${pad.bottom}px ${pad.left}px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>${columns}</tr></table></td></tr></table>`;
    })
    .join('\n');
  return `<!doctype html><html><head><meta charset="utf-8" /></head><body style="margin:0;background:#F4F4F5;font-family:Inter,Arial,sans-serif;color:#18181B"><div style="max-width:600px;margin:0 auto;background:#FFFFFF">${sections}</div></body></html>`;
}

/** Doc → plain-text sibling approximation (Phase B derives server-side). */
export function renderDocumentText(doc: TemplateDocument, facts: Record<string, string>): string {
  const lines: string[] = [];
  for (const section of doc.sections) {
    for (const column of section.columns) {
      for (const block of column.blocks) {
        switch (block.type) {
          case 'heading':
            lines.push(renderMergeTokens(block.text, facts, 'send'));
            break;
          case 'text':
            lines.push(
              renderMergeTokens(block.html.replace(/<[^>]+>/g, ' '), facts, 'send').replace(/\s+/g, ' ').trim(),
            );
            break;
          case 'button':
            lines.push(
              `${renderMergeTokens(block.label, facts, 'send')}: ${renderMergeTokens(block.href, facts, 'send')}`,
            );
            break;
          default:
            break;
        }
      }
    }
  }
  return lines.filter(Boolean).join('\n\n');
}
