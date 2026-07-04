import { toCsv } from '@/lib/csv';
import {
  collectMergeTokens,
  createBlankDocument,
  createBlankDocumentDoc,
  createBlock,
  createSection,
  newDocId,
} from '@/lib/template-doc';
import { renderDocumentHtml, renderDocumentText, renderMergeTokens } from '@/lib/template-render';
import type { ListQuery, ListResult } from '@/types/resource';
import {
  TEMPLATE_SCHEMA_VERSION,
  isCanvasDoc,
  type AnyTemplateDoc,
  type Template,
  type TemplateContext,
  type TemplateDocument,
  type TemplateInput,
  type TemplateListItem,
} from '@/types/templates';
import type {
  CanvasPreviewInput,
  DocumentPreviewInput,
  TemplateEngineService,
  TemplatePreview,
} from './template-service';

const LATENCY_MS = 250;

function delay<T>(value: T): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), LATENCY_MS));
}

// ---------------------------------------------------------------------------
// Contexts (mirrors the Phase-B code-side registry — D11)
// ---------------------------------------------------------------------------

const CONTEXTS: TemplateContext[] = [
  {
    key: 'auth.password_reset',
    label: 'Auth · Password reset',
    factSources: ['recipient'],
    facts: [
      { key: 'recipient.firstName', label: 'Recipient first name', sample: 'Alex' },
      { key: 'recipient.email', label: 'Recipient email', sample: 'alex@example.com' },
      { key: 'tenant.name', label: 'Tenant name', sample: 'Acme Events' },
      { key: 'resetLink', label: 'Reset link', sample: 'https://acme.foundryxems.com/change-password?token=sample' },
      { key: 'expiresInMinutes', label: 'Link expiry (minutes)', sample: '60' },
    ],
    requiredFacts: ['resetLink'],
  },
  {
    key: 'auth.invite',
    label: 'Auth · User invitation',
    factSources: ['recipient', 'actor'],
    facts: [
      { key: 'recipient.firstName', label: 'Recipient first name', sample: 'Alex' },
      { key: 'recipient.email', label: 'Recipient email', sample: 'alex@example.com' },
      { key: 'actor.name', label: 'Invited by', sample: 'Jordan Lee' },
      { key: 'tenant.name', label: 'Tenant name', sample: 'Acme Events' },
      { key: 'inviteLink', label: 'Invitation link', sample: 'https://acme.foundryxems.com/change-password?token=sample' },
    ],
    requiredFacts: ['inviteLink'],
  },
  {
    key: 'account.email_change_approve',
    label: 'Account · Email change (approve, old mailbox)',
    factSources: ['recipient'],
    facts: [
      { key: 'recipient.firstName', label: 'Recipient first name', sample: 'Alex' },
      { key: 'newEmail', label: 'Requested new email', sample: 'alex.new@example.com' },
      { key: 'approveLink', label: 'Approve link', sample: 'https://acme.foundryxems.com/approve-email-change?token=sample' },
    ],
    requiredFacts: ['approveLink'],
  },
  {
    key: 'account.email_change_verify',
    label: 'Account · Email change (verify, new mailbox)',
    factSources: ['recipient'],
    facts: [
      { key: 'recipient.firstName', label: 'Recipient first name', sample: 'Alex' },
      { key: 'verifyLink', label: 'Verify link', sample: 'https://acme.foundryxems.com/verify-email-change?token=sample' },
    ],
    requiredFacts: ['verifyLink'],
  },
  {
    key: 'tenant.provisioned',
    label: 'Tenant · Welcome / provisioned',
    factSources: ['recipient', 'record:tenant'],
    facts: [
      { key: 'recipient.firstName', label: 'Recipient first name', sample: 'Alex' },
      { key: 'record.name', label: 'Tenant name', sample: 'Acme Events' },
      { key: 'record.slug', label: 'Tenant slug', sample: 'acme' },
      { key: 'signinLink', label: 'Sign-in link', sample: 'https://acme.foundryxems.com/signin' },
    ],
    requiredFacts: ['signinLink'],
  },
  {
    key: 'status.notification',
    label: 'Status engine · Transition notification',
    factSources: ['actor', 'record:tenant'],
    facts: [
      { key: 'actor.name', label: 'Actor name', sample: 'Jordan Lee' },
      { key: 'record.name', label: 'Record name', sample: 'Acme Events' },
      { key: 'fromStatus', label: 'From status', sample: 'Active' },
      { key: 'toStatus', label: 'To status', sample: 'Suspended' },
    ],
    requiredFacts: [],
  },
  // Document surface (F2 D9) — sample invoice context exercising list facts.
  {
    key: 'document.invoice_preview',
    label: 'Document · Invoice (preview)',
    factSources: [],
    facts: [
      { key: 'companyName', label: 'Company name', sample: 'Acme Events' },
      { key: 'recipientName', label: 'Bill-to name', sample: 'Jordan Lee' },
      { key: 'invoiceNumber', label: 'Invoice number', sample: 'INV-2026-0042' },
      { key: 'subtotal', label: 'Subtotal', sample: '$1,200.00' },
      { key: 'tax', label: 'Tax', sample: '$72.00' },
      { key: 'total', label: 'Total', sample: '$1,272.00' },
    ],
    listFacts: [
      {
        key: 'lineItems',
        label: 'Line items',
        itemFacts: [
          { key: 'description', label: 'Description', sample: 'Conference pass' },
          { key: 'quantity', label: 'Quantity', sample: '2' },
          { key: 'unitPrice', label: 'Unit price', sample: '$600.00' },
          { key: 'amount', label: 'Amount', sample: '$1,200.00' },
        ],
      },
    ],
    requiredFacts: [],
  },
];

// ---------------------------------------------------------------------------
// Seeded system templates (platform tier)
// ---------------------------------------------------------------------------

function systemDoc(opts: { heading: string; body: string; buttonLabel: string; buttonHref: string }): TemplateDocument {
  const doc = createBlankDocument();
  const body = doc.sections[1];
  const heading = createBlock('heading');
  if (heading.type === 'heading') heading.text = opts.heading;
  const text = createBlock('text');
  if (text.type === 'text') text.html = opts.body;
  const button = createBlock('button');
  if (button.type === 'button') {
    button.label = opts.buttonLabel;
    button.href = opts.buttonHref;
  }
  body.columns[0].blocks.push(heading, text, button);
  return doc;
}

/** Starter platform document (basic invoice: header + line-item table + totals). */
function invoiceDoc(): TemplateDocument {
  const doc = createBlankDocumentDoc();
  const body = doc.sections[1];

  const heading = createBlock('heading');
  if (heading.type === 'heading') {
    heading.text = 'Invoice {{invoiceNumber}}';
    heading.level = 1;
  }
  const billTo = createBlock('text');
  if (billTo.type === 'text') billTo.html = 'Bill to: {{recipientName}}';

  const table = createBlock('table');
  if (table.type === 'table') {
    table.source = 'lineItems';
    table.columns = [
      { key: 'description', header: 'Description', align: 'left', width: null },
      { key: 'quantity', header: 'Qty', align: 'center', width: null },
      { key: 'unitPrice', header: 'Unit price', align: 'right', width: null },
      { key: 'amount', header: 'Amount', align: 'right', width: null },
    ];
    table.footer = [
      { cells: [{ text: 'Subtotal', align: 'right', span: 3 }, { text: '{{subtotal}}', align: 'right', span: 1 }] },
      { cells: [{ text: 'Tax', align: 'right', span: 3 }, { text: '{{tax}}', align: 'right', span: 1 }] },
      { cells: [{ text: 'Total', align: 'right', span: 3 }, { text: '{{total}}', align: 'right', span: 1 }] },
    ];
  }

  body.columns[0].blocks.push(heading, billTo, table);
  return doc;
}

function seedTemplates(): Template[] {
  const now = new Date().toISOString();
  const makeTyped = (
    key: string,
    name: string,
    type: Template['type'],
    context: string,
    subject: string,
    doc: TemplateDocument,
  ): Template => ({
    id: newDocId('tpl'),
    key,
    name,
    type,
    context,
    contextLabel: CONTEXTS.find((c) => c.key === context)?.label ?? context,
    tier: 'default',
    isSystem: true,
    subject,
    doc,
    createdAt: now,
    updatedAt: now,
  });
  const make = (
    key: string,
    name: string,
    context: string,
    subject: string,
    doc: TemplateDocument,
  ): Template => makeTyped(key, name, 'email', context, subject, doc);

  return [
    make(
      'auth.password_reset',
      'Password reset',
      'auth.password_reset',
      'Reset your {{tenant.name}} password',
      systemDoc({
        heading: 'Hi {{recipient.firstName}},',
        body: 'We received a request to reset your password. The link below is valid for {{expiresInMinutes}} minutes. If you did not request this, you can safely ignore this email.',
        buttonLabel: 'Reset password',
        buttonHref: '{{resetLink}}',
      }),
    ),
    make(
      'auth.invite',
      'User invitation',
      'auth.invite',
      "You've been invited to {{tenant.name}}",
      systemDoc({
        heading: 'Welcome, {{recipient.firstName}}!',
        body: '{{actor.name}} invited you to join {{tenant.name}}. Click below to claim your account and set a password.',
        buttonLabel: 'Accept invitation',
        buttonHref: '{{inviteLink}}',
      }),
    ),
    make(
      'account.email_change_approve',
      'Email change — approve (old mailbox)',
      'account.email_change_approve',
      'Approve your email change request',
      systemDoc({
        heading: 'Hi {{recipient.firstName}},',
        body: 'You asked to change your sign-in email to <b>{{newEmail}}</b>. Approve this request from your current mailbox to continue.',
        buttonLabel: 'Approve change',
        buttonHref: '{{approveLink}}',
      }),
    ),
    make(
      'account.email_change_verify',
      'Email change — verify (new mailbox)',
      'account.email_change_verify',
      'Verify your new email address',
      systemDoc({
        heading: 'Almost there, {{recipient.firstName}}',
        body: 'Confirm this mailbox to complete your email change.',
        buttonLabel: 'Verify email',
        buttonHref: '{{verifyLink}}',
      }),
    ),
    make(
      'tenant.provisioned',
      'Tenant welcome',
      'tenant.provisioned',
      'Welcome to {{record.name}}',
      systemDoc({
        heading: 'Your workspace is ready',
        body: 'Hi {{recipient.firstName}}, the workspace <b>{{record.name}}</b> has been provisioned. Sign in below to get started.',
        buttonLabel: 'Sign in',
        buttonHref: '{{signinLink}}',
      }),
    ),
    // Document surface (F2 D9) — starter platform invoice (PDF render target).
    makeTyped(
      'document.invoice',
      'Invoice',
      'document',
      'document.invoice_preview',
      'Invoice {{invoiceNumber}}',
      invoiceDoc(),
    ),
  ];
}

let templates: Template[] = seedTemplates();

function toListItem(t: Template): TemplateListItem {
  return {
    id: t.id,
    key: t.key,
    name: t.name,
    type: t.type,
    context: t.context,
    contextLabel: t.contextLabel,
    tier: t.tier,
    isSystem: t.isSystem,
    subject: t.subject,
    updatedAt: t.updatedAt,
    createdAt: t.createdAt,
  };
}

function applyQuery(items: TemplateListItem[], query: ListQuery): ListResult<TemplateListItem> {
  let rows = [...items];
  if (query.search) {
    const q = query.search.toLowerCase();
    rows = rows.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        r.key.toLowerCase().includes(q) ||
        r.subject.toLowerCase().includes(q),
    );
  }
  if (query.sort) {
    const { id, desc } = query.sort;
    rows.sort((a, b) => {
      const av = String((a as unknown as Record<string, unknown>)[id] ?? '');
      const bv = String((b as unknown as Record<string, unknown>)[id] ?? '');
      return desc ? bv.localeCompare(av) : av.localeCompare(bv);
    });
  }
  const total = rows.length;
  const start = query.page * query.pageSize; // ListQuery.page is 0-based
  return { data: rows.slice(start, start + query.pageSize), total, page: query.page };
}

function sampleFacts(contextKey: string): Record<string, string> {
  const context = CONTEXTS.find((c) => c.key === contextKey);
  return Object.fromEntries((context?.facts ?? []).map((f) => [f.key, f.sample]));
}

function validateRequiredFacts(input: TemplateInput): void {
  const context = CONTEXTS.find((c) => c.key === input.context);
  if (!context) throw new Error(`Unknown template context "${input.context}".`);
  // Canvas (badge) docs validate through validateCanvasDoc (lib/canvas-doc), not
  // the block-doc token collector — skip here.
  if (isCanvasDoc(input.doc)) return;
  const used = collectMergeTokens(input.doc, input.subject);
  const missing = context.requiredFacts.filter((f) => !used.has(f));
  if (missing.length) {
    throw new Error(
      `Required merge field${missing.length > 1 ? 's' : ''} missing: ${missing
        .map((m) => `{{${m}}}`)
        .join(', ')}. Add them to the design before saving.`,
    );
  }
}

export const mockTemplateEngineService: TemplateEngineService = {
  listTemplates(query: ListQuery): Promise<ListResult<TemplateListItem>> {
    return delay(applyQuery(templates.map(toListItem), query));
  },

  getTemplate(id: string): Promise<Template | null> {
    return delay(templates.find((t) => t.id === id) ?? null);
  },

  getAt(query: ListQuery, index: number) {
    const full = applyQuery(templates.map(toListItem), { ...query, page: 0, pageSize: 10_000 });
    return delay({ template: full.data[index] ?? null, total: full.total });
  },

  listContexts(): Promise<TemplateContext[]> {
    return delay(CONTEXTS);
  },

  listTemplateOptions(context: string): Promise<TemplateListItem[]> {
    return delay(templates.map(toListItem).filter((t) => t.context === context));
  },

  async createTemplate(input: TemplateInput): Promise<Template> {
    validateRequiredFacts(input);
    const now = new Date().toISOString();
    const created: Template = {
      id: newDocId('tpl'),
      key: `custom.${newDocId('k')}`,
      name: input.name,
      type: input.type ?? 'email',
      context: input.context,
      contextLabel: CONTEXTS.find((c) => c.key === input.context)?.label ?? input.context,
      tier: 'customized',
      isSystem: false,
      subject: input.subject,
      doc: input.doc,
      createdAt: now,
      updatedAt: now,
    };
    templates = [created, ...templates];
    return delay(created);
  },

  async updateTemplate(id: string, input: TemplateInput): Promise<Template> {
    validateRequiredFacts(input);
    const existing = templates.find((t) => t.id === id);
    if (!existing) return Promise.reject(new Error('Template not found.'));
    const updated: Template = {
      ...existing,
      name: input.name,
      subject: input.subject,
      doc: input.doc,
      // Two-tier D6: first edit of a platform-default row forks it.
      tier: 'customized',
      updatedAt: new Date().toISOString(),
    };
    templates = templates.map((t) => (t.id === id ? updated : t));
    return delay(updated);
  },

  deleteTemplate(id: string): Promise<void> {
    const target = templates.find((t) => t.id === id);
    if (target?.isSystem) return Promise.reject(new Error('System templates cannot be deleted.'));
    templates = templates.filter((t) => t.id !== id);
    return delay(undefined);
  },

  duplicateTemplate(id: string): Promise<Template> {
    const source = templates.find((t) => t.id === id);
    if (!source) return Promise.reject(new Error('Template not found.'));
    const now = new Date().toISOString();
    const copy: Template = {
      ...source,
      id: newDocId('tpl'),
      key: `custom.${newDocId('k')}`,
      name: `${source.name} (copy)`,
      tier: 'customized',
      isSystem: false,
      createdAt: now,
      updatedAt: now,
      doc: JSON.parse(JSON.stringify(source.doc)) as AnyTemplateDoc,
    };
    templates = [copy, ...templates];
    return delay(copy);
  },

  resetTemplate(id: string): Promise<Template> {
    const target = templates.find((t) => t.id === id);
    if (!target?.isSystem) return Promise.reject(new Error('Only system templates reset to the platform default.'));
    const fresh = seedTemplates().find((t) => t.key === target.key);
    if (!fresh) return Promise.reject(new Error('Platform default not found.'));
    const reset: Template = { ...fresh, id: target.id, createdAt: target.createdAt };
    templates = templates.map((t) => (t.id === id ? reset : t));
    return delay(reset);
  },

  preview(doc: TemplateDocument, contextKey: string, subject: string): Promise<TemplatePreview> {
    const facts = sampleFacts(contextKey);
    return delay({
      subject: renderMergeTokens(subject, facts),
      html: renderDocumentHtml(doc, facts),
      text: renderDocumentText(doc, facts),
    });
  },

  previewDocumentPdf(): Promise<Blob> {
    // A minimal but VALID single-page PDF — enough for the embedded <iframe>
    // viewer + vitest. The real backend returns WeasyPrint bytes.
    const pdf =
      '%PDF-1.4\n' +
      '1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n' +
      '2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n' +
      '3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n' +
      'trailer<</Root 1 0 R>>\n' +
      '%%EOF';
    return delay(new Blob([pdf], { type: 'application/pdf' }));
  },

  previewDocumentHtml(input: DocumentPreviewInput): Promise<string> {
    const facts = sampleFacts(input.context);
    return delay(renderDocumentHtml(input.doc, facts));
  },

  previewCanvasPdf(): Promise<Blob> {
    const pdf =
      '%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n' +
      '2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n' +
      '3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 244 153]>>endobj\n' +
      'trailer<</Root 1 0 R>>\n%%EOF';
    return delay(new Blob([pdf], { type: 'application/pdf' }));
  },

  previewCanvasHtml(input: CanvasPreviewInput): Promise<string> {
    // A bare stand-in sheet for vitest; the real backend renders the canvas.
    const names = input.doc.sides.map((s) => s.name).join(', ');
    return delay(`<!DOCTYPE html><html><body><div class="badge-side">${names}</div></body></html>`);
  },

  testSend(id: string): Promise<{ toEmail: string }> {
    const target = templates.find((t) => t.id === id);
    if (!target) return Promise.reject(new Error('Template not found.'));
    return delay({ toEmail: 'you@example.com' });
  },

  exportTemplates(query: ListQuery, columns: string[]): Promise<string> {
    const { data } = applyQuery(templates.map(toListItem), { ...query, page: 0, pageSize: 10_000 });
    const rows = data.map((t) =>
      columns.map((c) => String((t as unknown as Record<string, unknown>)[c] ?? '')),
    );
    return delay(toCsv(columns, rows));
  },
};

/** Test hook — reset the in-memory store between Vitest cases. */
export function __resetMockTemplates(): void {
  templates = seedTemplates();
}

export { CONTEXTS as MOCK_TEMPLATE_CONTEXTS };
export const __schemaVersion = TEMPLATE_SCHEMA_VERSION;
export const __createSection = createSection;
