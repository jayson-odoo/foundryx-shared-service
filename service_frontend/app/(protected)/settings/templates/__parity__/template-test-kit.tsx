/**
 * Shared fixtures and service stand-ins for the templates pages' switch-off
 * parity tests and their switch-on request tests (Foundryx UIUX, slice
 * W4-TEMPLATES). Every service call lands in `calls` with its arguments, so a
 * test can compare what reached the backend with the switch off and with it on.
 */
import { act } from '@testing-library/react';
import { parityHtml as baseParityHtml } from '@/components/fx/__parity__/parity-utils';
import type { Template, TemplateContext, TemplateDocument, TemplateListItem } from '@/types/templates';

export const calls: unknown[][] = [];

export function resetCalls(): void {
  calls.length = 0;
}

/** Only the calls that write data or send something (no reads, no toasts). */
export const WRITE_CALLS = new Set([
  'template.create',
  'template.update',
  'template.duplicate',
  'template.testSend',
  'template.delete',
  'template.reset',
  'pending.park',
]);

export function writeCalls(): unknown[][] {
  return calls.filter((c) => WRITE_CALLS.has(String(c[0])));
}

/** React 19's `_r_N_` ids renamed in order, and timings and mid-animation styles masked. */
export function parityHtml(root: Element): string {
  const seen = new Map<string, string>();
  return baseParityHtml(root)
    .replace(/_r_[0-9a-z]+_/g, (id) => {
      if (!seen.has(id)) seen.set(id, `_rid${seen.size}_`);
      return seen.get(id) as string;
    })
    .replace(/(animation|transition)-duration:\s*[0-9.]+m?s/g, '$1-duration: <t>')
    // Radix sets a tab's animation style only when it catches the animation
    // mid-way, so whether the attribute is filled is timing, not markup.
    .replace(/style="(animation-duration: <t>;)?"/g, 'style="<anim>"');
}

export async function settle(ms = 50): Promise<void> {
  await act(async () => {
    await new Promise((r) => setTimeout(r, ms));
  });
}

/**
 * A repeatable `Math.random` (the document's new block and section ids come
 * from it), so a new template's blank document is the same in every run.
 */
export function seededRandom(): () => number {
  let s = 42;
  return () => {
    s = (s * 16807) % 2147483647;
    return s / 2147483647;
  };
}

// --- fixtures ---------------------------------------------------------------

export function templateDoc(): TemplateDocument {
  return {
    schemaVersion: 1,
    sections: [
      {
        id: 'sec_head',
        layout: '100',
        background: null,
        padding: { top: 0, bottom: 0, left: 0, right: 0 },
        columns: [{ id: 'col_head', blocks: [{ id: 'blk_brand', type: 'brandHeader', overrides: null }] }],
      },
      {
        id: 'sec_body',
        layout: '100',
        background: '#FFFFFF',
        padding: { top: 16, bottom: 16, left: 24, right: 24 },
        columns: [
          {
            id: 'col_body',
            blocks: [
              { id: 'blk_head', type: 'heading', text: 'Welcome, {{recipient.firstName}}', level: 2, align: 'left' },
              { id: 'blk_text', type: 'text', html: 'Your account is <b>ready</b>.', align: 'left' },
            ],
          },
        ],
      },
      {
        id: 'sec_foot',
        layout: '100',
        background: null,
        padding: { top: 0, bottom: 0, left: 0, right: 0 },
        columns: [{ id: 'col_foot', blocks: [{ id: 'blk_footer', type: 'brandFooter', overrides: null }] }],
      },
    ],
  };
}

export function template(overrides: Partial<Template> = {}): Template {
  return {
    id: 'tpl-1',
    key: 'auth.welcome',
    name: 'Welcome email',
    type: 'email',
    context: 'auth.user',
    contextLabel: 'User account',
    tier: 'customized',
    isSystem: false,
    subject: 'Welcome to {{tenant.name}}',
    updatedAt: '2026-11-12T06:14:00Z',
    createdAt: '2026-10-01T02:00:00Z',
    doc: templateDoc(),
    ...overrides,
  };
}

export function listItem(t: Template): TemplateListItem {
  const { doc: _doc, ...rest } = t;
  void _doc;
  return rest;
}

export const CONTEXTS: TemplateContext[] = [
  {
    key: 'auth.user',
    label: 'User account',
    factSources: [],
    facts: [
      { key: 'recipient.firstName', label: 'First name', sample: 'Alex' },
      { key: 'tenant.name', label: 'Workspace name', sample: 'Maju' },
    ],
    requiredFacts: [],
  },
  {
    key: 'document.invoice',
    label: 'Invoice',
    factSources: [],
    facts: [{ key: 'invoice.number', label: 'Invoice number', sample: 'INV-1' }],
    listFacts: [],
    requiredFacts: [],
  },
];

export const answers = {
  template: template(),
  list: [template(), template({ id: 'tpl-2', key: 'auth.reset', name: 'Password reset', isSystem: true, tier: 'default' })],
};

const ok = <T,>(value: T) => Promise.resolve(value);

function rec<A extends unknown[], R>(name: string, fn: (...args: A) => R) {
  return (...args: A): R => {
    calls.push([name, ...JSON.parse(JSON.stringify(args ?? []))]);
    return fn(...args);
  };
}

export const templateServiceMock = {
  templateEngineService: {
    listTemplates: () => ok({ data: answers.list.map(listItem), total: answers.list.length }),
    getTemplate: (id: string) => ok([answers.template, ...answers.list].find((t) => t.id === id) ?? null),
    getAt: () => ok({ template: listItem(answers.template), total: 2 }),
    listContexts: () => ok(CONTEXTS),
    listTemplateOptions: () => ok([]),
    createTemplate: rec('template.create', (input: { name: string; subject: string; context: string }) =>
      ok(template({ id: 'tpl-9', name: input.name, subject: input.subject, context: input.context })),
    ),
    updateTemplate: rec('template.update', (id: string, input: { name: string; subject: string; context: string }) =>
      ok({ ...answers.template, id, name: input.name, subject: input.subject, context: input.context }),
    ),
    deleteTemplate: rec('template.delete', () => ok(undefined)),
    duplicateTemplate: rec('template.duplicate', () => ok(template({ id: 'tpl-3', name: 'Welcome email (copy)' }))),
    resetTemplate: rec('template.reset', () => ok(answers.template)),
    testSend: rec('template.testSend', () => ok({ toEmail: 'kay@maju.my' })),
    preview: (_doc: unknown, context: string, subject: string) => {
      calls.push(['template.preview', context, subject]);
      return ok({ subject: subject.replace('{{tenant.name}}', 'Maju'), html: '<p>Rendered</p>', text: 'Rendered' });
    },
    previewDocumentPdf: () => ok(new Blob()),
    previewDocumentHtml: () => ok('<p>Doc</p>'),
    previewCanvasPdf: () => ok(new Blob()),
    previewCanvasHtml: () => ok('<p>Canvas</p>'),
    exportTemplates: rec('template.export', () => ok('')),
  },
};

export const ruleEngineServiceMock = {
  ruleEngineService: {
    getFacts: () => ok([]),
    listRules: () => ok({ data: [], total: 0 }),
  },
};

export const pendingActionsServiceMock = {
  pendingActionsService: {
    park: rec('pending.park', () =>
      ok({ id: 'pa-1', status: 'PENDING', executeAt: new Date(Date.now() + 10_000).toISOString(), windowSeconds: 10 }),
    ),
    cancel: () => ok({ id: 'pa-1', status: 'CANCELLED' }),
    current: () => ok({ pending: null }),
  },
};

export const preferencesServiceMock = {
  preferencesService: {
    get: () => ok(null),
    save: () => ok(undefined),
  },
};

const toastFn = (kind: string) => (...args: unknown[]) => {
  calls.push([`toast.${kind}`, ...args]);
  return 'toast-id';
};

export const toastMock = {
  toast: {
    success: toastFn('success'),
    error: toastFn('error'),
    info: toastFn('info'),
    warning: toastFn('warning'),
    message: toastFn('message'),
    custom: toastFn('custom'),
    dismiss: toastFn('dismiss'),
    fxDone: toastFn('fxDone'),
  },
};
