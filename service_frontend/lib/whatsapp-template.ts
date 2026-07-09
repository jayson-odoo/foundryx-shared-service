/**
 * WhatsApp template transform + validation (plan 07) — parity mirror of the
 * backend `template_schemas.py`. `toMetaComponents` / `fromMetaComponents` are
 * the single bidirectional transform; `validateDoc` mirrors the save/submit
 * 422 gate so the builder shows per-field errors before hitting the server.
 * Pinned to the backend by a parity test.
 */
import type {
  ButtonType,
  HeaderFormat,
  TemplateCategory,
  WaButton,
  WaHeader,
  WaTemplateDoc,
} from '@/types/whatsapp-template';

export const TEMPLATE_CATEGORIES: TemplateCategory[] = ['MARKETING', 'UTILITY'];
export const HEADER_FORMATS: HeaderFormat[] = ['TEXT', 'IMAGE', 'VIDEO', 'DOCUMENT'];
export const MEDIA_HEADER_FORMATS = ['IMAGE', 'VIDEO', 'DOCUMENT'] as const;
export const BUTTON_TYPES: ButtonType[] = ['QUICK_REPLY', 'URL', 'PHONE_NUMBER', 'COPY_CODE'];
export const TEMPLATE_LANGUAGES = [
  'en', 'en_US', 'en_GB', 'es', 'es_ES', 'es_MX', 'pt_BR', 'pt_PT', 'fr', 'de',
  'it', 'nl', 'id', 'ms', 'zh_CN', 'zh_HK', 'zh_TW', 'ja', 'ko', 'th', 'vi',
  'ar', 'hi', 'ta', 'ru', 'tr',
];
export const MAX_BUTTONS = 10;

const NAME_RE = /^[a-z0-9_]{1,512}$/;
const VAR_RE = /\{\{\s*(\d+)\s*\}\}/g;
const URL_RE = /^https?:\/\//i;
const PHONE_RE = /^\+?[0-9][0-9\-\s]{4,19}$/;

export function distinctVarCount(text: string): number {
  const set = new Set<number>();
  for (const m of Array.from((text || '').matchAll(VAR_RE))) set.add(Number(m[1]));
  return set.size;
}

/** True when {{n}} placeholders are exactly {{1}}..{{N}} (Meta requires it;
 * our example arrays are positional). Mirror of backend `vars_sequential`. */
export function varsSequential(text: string): boolean {
  const nums = new Set<number>();
  for (const m of Array.from((text || '').matchAll(VAR_RE))) nums.add(Number(m[1]));
  if (nums.size === 0) return true;
  for (let i = 1; i <= nums.size; i++) if (!nums.has(i)) return false;
  return true;
}

/** Meta rejects a body that ENDS with a variable. Mirror of backend `ends_with_var`. */
export function endsWithVar(text: string): boolean {
  return /\{\{\s*\d+\s*\}\}\s*$/.test(text || '');
}

/** Meta rejects two adjacent variables. Mirror of backend `has_adjacent_vars`. */
export function hasAdjacentVars(text: string): boolean {
  return /\}\}\s*\{\{/.test(text || '');
}

type MetaComponent = Record<string, unknown>;

export function toMetaComponents(doc: WaTemplateDoc): MetaComponent[] {
  const components: MetaComponent[] = [];

  if (doc.header) {
    if (doc.header.format === 'TEXT') {
      const comp: MetaComponent = { type: 'HEADER', format: 'TEXT', text: doc.header.text || '' };
      // Only emit the example when the text actually has a variable (a stale
      // example on a var-less header is a Meta format rejection).
      if (doc.header.example && distinctVarCount(doc.header.text || '') >= 1) {
        comp.example = { header_text: [doc.header.example] };
      }
      components.push(comp);
    } else {
      const comp: MetaComponent = { type: 'HEADER', format: doc.header.format };
      if (doc.header.sampleKey) comp.example = { header_handle: [doc.header.sampleKey] };
      components.push(comp);
    }
  }

  const bodyComp: MetaComponent = { type: 'BODY', text: doc.body.text };
  if (doc.body.examples && doc.body.examples.length) {
    bodyComp.example = { body_text: [[...doc.body.examples]] };
  }
  components.push(bodyComp);

  if (doc.footer && doc.footer.text) components.push({ type: 'FOOTER', text: doc.footer.text });

  if (doc.buttons && doc.buttons.length) {
    const metaButtons: MetaComponent[] = [];
    for (const b of doc.buttons) {
      if (b.type === 'QUICK_REPLY') metaButtons.push({ type: 'QUICK_REPLY', text: b.text || '' });
      else if (b.type === 'URL') {
        const mb: MetaComponent = { type: 'URL', text: b.text || '', url: b.url || '' };
        if (b.example) mb.example = [b.example];
        metaButtons.push(mb);
      } else if (b.type === 'PHONE_NUMBER')
        metaButtons.push({ type: 'PHONE_NUMBER', text: b.text || '', phone_number: b.phoneNumber || '' });
      else if (b.type === 'COPY_CODE') metaButtons.push({ type: 'COPY_CODE', example: b.example || '' });
    }
    if (metaButtons.length) components.push({ type: 'BUTTONS', buttons: metaButtons });
  }

  return components;
}

export function fromMetaComponents(
  components: MetaComponent[] | null | undefined,
  meta: { name: string; category: TemplateCategory; language: string },
): WaTemplateDoc {
  let header: WaHeader | null = null;
  let body = { text: '', examples: [] as string[] };
  let footer: { text: string } | null = null;
  const buttons: WaButton[] = [];

  for (const c of components || []) {
    const ctype = String(c.type || '').toUpperCase();
    if (ctype === 'HEADER') {
      const fmt = String(c.format || 'TEXT').toUpperCase();
      const example = (c.example as Record<string, unknown>) || {};
      if (fmt === 'TEXT') {
        const ex = (example.header_text as string[]) || [];
        header = { format: 'TEXT', text: String(c.text || ''), example: ex[0] ?? null };
      } else if (fmt === 'IMAGE' || fmt === 'VIDEO' || fmt === 'DOCUMENT') {
        const handle = (example.header_handle as string[]) || [];
        header = { format: fmt, sampleKey: handle[0] ?? null };
      }
    } else if (ctype === 'BODY') {
      const example = (c.example as Record<string, unknown>) || {};
      const bt = (example.body_text as string[][]) || [];
      body = { text: String(c.text || ''), examples: Array.isArray(bt[0]) ? [...bt[0]] : [] };
    } else if (ctype === 'FOOTER') {
      footer = { text: String(c.text || '') };
    } else if (ctype === 'BUTTONS') {
      for (const b of (c.buttons as MetaComponent[]) || []) {
        const bt = String(b.type || '').toUpperCase();
        if (bt === 'QUICK_REPLY') buttons.push({ type: 'QUICK_REPLY', text: (b.text as string) ?? null });
        else if (bt === 'URL') {
          const ex = (b.example as string[]) || [];
          buttons.push({ type: 'URL', text: (b.text as string) ?? null, url: (b.url as string) ?? null, example: ex[0] ?? null });
        } else if (bt === 'PHONE_NUMBER')
          buttons.push({ type: 'PHONE_NUMBER', text: (b.text as string) ?? null, phoneNumber: (b.phone_number as string) ?? null });
        else if (bt === 'COPY_CODE') buttons.push({ type: 'COPY_CODE', example: (b.example as string) ?? null });
      }
    }
  }

  return {
    name: meta.name,
    category: meta.category,
    language: meta.language,
    header,
    body,
    footer,
    buttons: buttons.length ? buttons : null,
  };
}

/** Mirror of backend validate_doc → per-field error map (empty = valid). */
export function validateDoc(
  doc: WaTemplateDoc,
  existingNames?: Set<string>,
): Record<string, string> {
  const e: Record<string, string> = {};
  if (!NAME_RE.test(doc.name || '')) {
    e.name = 'Use lowercase letters, numbers and underscores (max 512).';
  } else if (existingNames && existingNames.has(doc.name)) {
    e.name = 'A template with this name already exists on this channel.';
  }
  if (!TEMPLATE_CATEGORIES.includes(doc.category)) e.category = 'Choose Marketing or Utility.';
  if (!TEMPLATE_LANGUAGES.includes(doc.language)) e.language = 'Choose a valid language.';

  if (doc.header && doc.header.format === 'TEXT') {
    const nvars = distinctVarCount(doc.header.text || '');
    if (nvars > 1) e.header = 'A text header allows at most one variable.';
    else if (nvars === 1 && !(doc.header.example || '').trim())
      e.header = 'Provide a sample value for the header variable.';
  }

  if (!(doc.body.text || '').trim()) {
    e.body = 'Body text is required.';
  } else if (!varsSequential(doc.body.text)) {
    e.body = 'Variables must be numbered sequentially: {{1}}, {{2}}, …';
  } else if (endsWithVar(doc.body.text)) {
    e.body = 'Body can’t end with a variable — add text after the last {{n}} (Meta rule).';
  } else if (hasAdjacentVars(doc.body.text)) {
    e.body = 'Two variables can’t be adjacent — put text between them (Meta rule).';
  } else {
    const nvars = distinctVarCount(doc.body.text);
    const provided = (doc.body.examples || []).filter((x) => (x || '').trim()).length;
    if (provided !== nvars) e.body = `Provide exactly ${nvars} sample value(s) for the body variables.`;
  }

  if (doc.buttons && doc.buttons.length) {
    if (doc.buttons.length > MAX_BUTTONS) {
      e.buttons = `At most ${MAX_BUTTONS} buttons.`;
    } else {
      for (let i = 0; i < doc.buttons.length; i++) {
        const b = doc.buttons[i];
        if (['QUICK_REPLY', 'URL', 'PHONE_NUMBER'].includes(b.type) && !(b.text || '').trim()) {
          e.buttons = `Button ${i + 1}: label is required.`;
          break;
        }
        if (b.type === 'URL' && !URL_RE.test((b.url || '').trim())) {
          e.buttons = `Button ${i + 1}: enter a valid http(s) URL.`;
          break;
        }
        if (b.type === 'PHONE_NUMBER' && !PHONE_RE.test((b.phoneNumber || '').trim())) {
          e.buttons = `Button ${i + 1}: enter a valid phone number.`;
          break;
        }
        if (b.type === 'COPY_CODE' && !(b.example || '').trim()) {
          e.buttons = `Button ${i + 1}: provide a sample code.`;
          break;
        }
      }
    }
  }
  return e;
}

/** GREEN/YELLOW/RED → High/Medium/Low display (plan 07 BR-7). */
export function qualityLabel(quality: string | null): string {
  switch ((quality || '').toUpperCase()) {
    case 'GREEN':
      return 'High';
    case 'YELLOW':
      return 'Medium';
    case 'RED':
      return 'Low';
    default:
      return '—';
  }
}
