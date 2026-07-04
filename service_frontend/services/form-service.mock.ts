/**
 * Mock form service (Phase A) — in-memory forms/versions/submissions with the
 * REAL contracts: publish runs `validateFormDoc` (422 problems), submit runs
 * the client validation mirror over the visible set (422 per-field map),
 * transitions walk the seeded scoped graph (D15). Latency on every call so
 * loading states are tunable.
 */
import { toCsv } from '@/lib/csv';
import { validateFormDoc, newId } from '@/lib/form-doc';
import { validateAll, visibleAnswers } from '@/lib/form-validate';
import type { ListQuery } from '@/types/resource';
import type {
  FormAnswers,
  FormCreatePayload,
  FormDetail,
  FormDocument,
  FormFillView,
  FormRow,
  FormSubmissionRow,
  FormUpdatePayload,
  FormVersionRow,
} from '@/types/forms';
import {
  FormPublishError,
  FormSubmitError,
  type FormService,
  type FormSubmissionGraph,
} from './form-service';

const LATENCY_MS = 250;

function delay<T>(value: T): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), LATENCY_MS));
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

const mins = (n: number) => new Date(Date.now() - n * 60_000).toISOString();

// ---- seeded documents ----

/** Multi-page speaker application: conditions + computed + the full taxonomy. */
const SPEAKER_DOC: FormDocument = {
  schemaVersion: 1,
  pages: [
    {
      id: 'pg_about',
      title: 'About you',
      sections: [
        {
          id: 'sec_id',
          title: 'Identity',
          twoColumn: true,
          fields: [
            { id: 'fld_name', type: 'text', key: 'fullName', label: 'Full name', required: true },
            { id: 'fld_email', type: 'email', key: 'email', label: 'Email', required: true },
            { id: 'fld_phone', type: 'phone', key: 'phone', label: 'Phone' },
            {
              id: 'fld_site',
              type: 'url',
              key: 'website',
              label: 'Website',
              placeholder: 'https://',
            },
          ],
        },
        {
          id: 'sec_addr',
          title: 'Address',
          fields: [
            { id: 'fld_addr', type: 'address', key: 'address', label: 'Address', required: true },
          ],
        },
      ],
    },
    {
      id: 'pg_talk',
      title: 'Your talk',
      sections: [
        {
          id: 'sec_talk',
          title: 'Proposal',
          fields: [
            {
              id: 'fld_track',
              type: 'select',
              key: 'track',
              label: 'Track',
              required: true,
              options: {
                kind: 'static',
                items: [
                  { value: 'engineering', label: 'Engineering' },
                  { value: 'design', label: 'Design' },
                  { value: 'product', label: 'Product' },
                ],
              },
            },
            {
              id: 'fld_workshop',
              type: 'yesno',
              key: 'isWorkshop',
              label: 'Is this a workshop?',
              required: true,
            },
            {
              id: 'fld_seats',
              type: 'number',
              key: 'seats',
              label: 'Workshop seats',
              number: { min: 5, max: 200 },
              conditionsJson: {
                kind: 'group',
                combinator: 'and',
                rules: [
                  {
                    kind: 'condition',
                    fact: 'answers.isWorkshop',
                    operator: 'is_true',
                    valueKind: 'literal',
                    value: null,
                  },
                ],
              },
            },
            {
              id: 'fld_fee',
              type: 'number',
              key: 'feePerSeat',
              label: 'Fee per seat',
              number: { min: 0 },
              conditionsJson: {
                kind: 'group',
                combinator: 'and',
                rules: [
                  {
                    kind: 'condition',
                    fact: 'answers.isWorkshop',
                    operator: 'is_true',
                    valueKind: 'literal',
                    value: null,
                  },
                ],
              },
            },
            {
              id: 'fld_revenue',
              type: 'computed',
              key: 'projectedRevenue',
              label: 'Projected revenue',
              computed: { expression: 'seats * feePerSeat' },
              conditionsJson: {
                kind: 'group',
                combinator: 'and',
                rules: [
                  {
                    kind: 'condition',
                    fact: 'answers.isWorkshop',
                    operator: 'is_true',
                    valueKind: 'literal',
                    value: null,
                  },
                ],
              },
            },
            {
              id: 'fld_abstract',
              type: 'textarea',
              key: 'abstract',
              label: 'Abstract',
              required: true,
              text: { minLength: 50, maxLength: 2000 },
            },
            {
              id: 'fld_topics',
              type: 'checkboxes',
              key: 'topics',
              label: 'Topics',
              options: {
                kind: 'static',
                items: [
                  { value: 'ai', label: 'AI' },
                  { value: 'web', label: 'Web' },
                  { value: 'cloud', label: 'Cloud' },
                  { value: 'data', label: 'Data' },
                ],
              },
            },
            {
              id: 'fld_speakers',
              type: 'repeater',
              key: 'coSpeakers',
              label: 'Co-speakers',
              repeater: {
                fields: [
                  { id: 'sub_name', type: 'text', key: 'name', label: 'Name', required: true },
                  { id: 'sub_email', type: 'email', key: 'email', label: 'Email', required: true },
                ],
                maxRows: 3,
              },
            },
          ],
        },
      ],
    },
    {
      id: 'pg_confirm',
      title: 'Confirm',
      sections: [
        {
          id: 'sec_confirm',
          fields: [
            { id: 'fld_head', type: 'heading', label: 'Almost done', heading: { level: 2 } },
            {
              id: 'fld_para',
              type: 'paragraph',
              label: 'Review your answers before submitting. Our committee replies within two weeks.',
            },
            { id: 'fld_div', type: 'divider', label: '' },
            {
              id: 'fld_rating',
              type: 'rating',
              key: 'excitement',
              label: 'How excited are you?',
              rating: { max: 5 },
            },
            {
              id: 'fld_date',
              type: 'date',
              key: 'availableFrom',
              label: 'Available from',
              required: true,
            },
            { id: 'fld_sig', type: 'signature', key: 'signature', label: 'Signature' },
          ],
        },
      ],
    },
  ],
};

const FEEDBACK_DOC: FormDocument = {
  schemaVersion: 1,
  pages: [
    {
      id: 'pg_1',
      title: '',
      sections: [
        {
          id: 'sec_1',
          title: 'Your feedback',
          fields: [
            {
              id: 'fld_rate',
              type: 'rating',
              key: 'overall',
              label: 'Overall rating',
              required: true,
              rating: { max: 5 },
            },
            {
              id: 'fld_comment',
              type: 'textarea',
              key: 'comments',
              label: 'Comments',
            },
          ],
        },
      ],
    },
  ],
};

// ---- seeded scoped graphs (D4 — per-form pipelines) ----

type MockGraph = FormSubmissionGraph;

function seedGraph(prefix: string, extra: boolean): MockGraph {
  const statuses = [
    {
      id: `${prefix}-st-draft`,
      key: 'draft',
      label: 'Draft',
      color: '#6B7280',
      isInitial: true,
      isActive: true,
      isTerminal: false,
    },
    {
      id: `${prefix}-st-submitted`,
      key: 'submitted',
      label: 'Submitted',
      color: '#3B82F6',
      isInitial: false,
      isActive: false,
      isTerminal: false,
    },
  ];
  const transitions = [
    {
      id: `${prefix}-tr-submit`,
      label: 'Submit',
      fromStatusId: `${prefix}-st-draft`,
      toStatusId: `${prefix}-st-submitted`,
    },
  ];
  if (extra) {
    statuses.push(
      {
        id: `${prefix}-st-review`,
        key: 'under_review',
        label: 'Under Review',
        color: '#F59E0B',
        isInitial: false,
        isActive: false,
        isTerminal: false,
      },
      {
        id: `${prefix}-st-accepted`,
        key: 'accepted',
        label: 'Accepted',
        color: '#22C55E',
        isInitial: false,
        isActive: false,
        isTerminal: true,
      },
      {
        id: `${prefix}-st-rejected`,
        key: 'rejected',
        label: 'Rejected',
        color: '#EF4444',
        isInitial: false,
        isActive: false,
        isTerminal: true,
      },
    );
    transitions.push(
      {
        id: `${prefix}-tr-review`,
        label: 'Start review',
        fromStatusId: `${prefix}-st-submitted`,
        toStatusId: `${prefix}-st-review`,
      },
      {
        id: `${prefix}-tr-accept`,
        label: 'Accept',
        fromStatusId: `${prefix}-st-review`,
        toStatusId: `${prefix}-st-accepted`,
      },
      {
        id: `${prefix}-tr-reject`,
        label: 'Reject',
        fromStatusId: `${prefix}-st-review`,
        toStatusId: `${prefix}-st-rejected`,
      },
    );
  }
  return { statuses, transitions };
}

// ---- in-memory state ----

/** `isTrashed` is derived from `archived` at read time (toRow). */
interface MockForm extends Omit<FormDetail, 'isTrashed'> {
  /** Published snapshots, newest last. */
  versionDocs: Record<string, FormDocument>;
  versionRows: FormVersionRow[];
  archived: boolean;
}

function seedForms(): MockForm[] {
  const base = {
    description: null as string | null,
    opensAt: null as string | null,
    closesAt: null as string | null,
    maxSubmissions: null as number | null,
    submissionLimitPerUser: null as number | null,
    pinnedColumns: [] as string[],
    displayMode: 'paged' as const,
    allowRevisions: false,
    archived: false,
  };
  return [
    {
      ...base,
      id: 'form-speaker',
      name: 'Speaker Application',
      slug: 'speaker-application',
      description: 'Call for papers — annual tech summit.',
      status: 'published',
      access: 'internal',
      currentVersionId: 'ver-speaker-2',
      currentVersionNumber: 2,
      hasUnpublishedChanges: false,
      pinnedColumns: ['fullName', 'track'],
      allowRevisions: true,
      draftDefinition: clone(SPEAKER_DOC),
      versionDocs: { 'ver-speaker-1': clone(SPEAKER_DOC), 'ver-speaker-2': clone(SPEAKER_DOC) },
      versionRows: [
        {
          id: 'ver-speaker-2',
          versionNumber: 2,
          publishedBy: 'usr-demo',
          publishedByName: 'Demo User',
          createdAt: mins(60 * 24 * 2),
        },
        {
          id: 'ver-speaker-1',
          versionNumber: 1,
          publishedBy: 'usr-demo',
          publishedByName: 'Demo User',
          createdAt: mins(60 * 24 * 9),
        },
      ],
      submissionCount: 5,
      createdAt: mins(60 * 24 * 10),
      updatedAt: mins(60 * 24 * 2),
    },
    {
      ...base,
      id: 'form-feedback',
      name: 'Attendee Feedback',
      slug: 'attendee-feedback',
      status: 'draft',
      access: 'internal',
      currentVersionId: null,
      currentVersionNumber: null,
      hasUnpublishedChanges: true,
      draftDefinition: clone(FEEDBACK_DOC),
      versionDocs: {},
      versionRows: [],
      submissionCount: 0,
      createdAt: mins(60 * 30),
      updatedAt: mins(60 * 5),
    },
    {
      ...base,
      id: 'form-archived',
      name: 'Volunteer Signup 2025',
      slug: 'volunteer-signup-2025',
      status: 'archived',
      access: 'internal',
      archived: true,
      currentVersionId: null,
      currentVersionNumber: null,
      hasUnpublishedChanges: false,
      draftDefinition: clone(FEEDBACK_DOC),
      versionDocs: {},
      versionRows: [],
      submissionCount: 0,
      createdAt: mins(60 * 24 * 200),
      updatedAt: mins(60 * 24 * 90),
    },
  ];
}

const graphs: Record<string, MockGraph> = {
  'form-speaker': seedGraph('spk', true),
  'form-feedback': seedGraph('fbk', false),
  'form-archived': seedGraph('arc', false),
};

function seedSubmissions(): FormSubmissionRow[] {
  const g = graphs['form-speaker'];
  const status = (key: string) => g.statuses.find((s) => s.key === key)!;
  const make = (
    n: number,
    key: string,
    name: string,
    answers: FormAnswers,
    overrides: Partial<FormSubmissionRow> = {},
  ): FormSubmissionRow => ({
    id: `sub-${n}`,
    formId: 'form-speaker',
    submissionGroupId: `sub-${n}`,
    revisionNumber: 1,
    isCurrent: true,
    versionId: 'ver-speaker-2',
    versionNumber: 2,
    statusId: status(key).id,
    statusKey: key,
    statusLabel: status(key).label,
    statusColor: status(key).color,
    userId: `usr-${n}`,
    userName: name,
    subjectType: null,
    subjectId: null,
    answers,
    submittedAt: key === 'draft' ? null : mins(n * 60 * 3),
    createdAt: mins(n * 60 * 4),
    updatedAt: mins(n * 30),
    availableTransitionIds: g.transitions
      .filter((t) => t.fromStatusId === status(key).id)
      .map((t) => t.id),
    ...overrides,
  });
  return [
    // A 2-revision group — rev 1 frozen (rejected), rev 2 current (submitted).
    // Demonstrates the history panel + "rev N" badge without a live revise.
    make(
      1,
      'submitted',
      'Aisha Rahman',
      {
        fullName: 'Aisha Rahman',
        email: 'aisha@example.com',
        track: 'engineering',
        isWorkshop: true,
        seats: 40,
        feePerSeat: 25,
        projectedRevenue: 1000,
        abstract:
          'A deep dive into building multi-tenant platforms with schema isolation and per-tenant theming — revised with a sharper workshop outline.',
        topics: ['ai', 'cloud'],
        address: { line1: '12 Jalan Api', city: 'Kuala Lumpur', country: 'MY' },
        availableFrom: '2026-08-01',
        excitement: 5,
      },
      { submissionGroupId: 'grp-aisha', revisionNumber: 2, isCurrent: true },
    ),
    make(
      11,
      'rejected',
      'Aisha Rahman',
      {
        fullName: 'Aisha Rahman',
        email: 'aisha@example.com',
        track: 'engineering',
        isWorkshop: true,
        seats: 20,
        feePerSeat: 25,
        projectedRevenue: 500,
        abstract: 'A deep dive into building multi-tenant platforms with schema isolation.',
        topics: ['ai'],
        address: { line1: '12 Jalan Api', city: 'Kuala Lumpur', country: 'MY' },
        availableFrom: '2026-08-01',
        excitement: 5,
      },
      {
        id: 'sub-1-r1',
        submissionGroupId: 'grp-aisha',
        revisionNumber: 1,
        isCurrent: false,
        versionId: 'ver-speaker-1',
        versionNumber: 1,
      },
    ),
    make(2, 'under_review', 'Ben Ortiz', {
      fullName: 'Ben Ortiz',
      email: 'ben@example.com',
      track: 'design',
      isWorkshop: false,
      abstract:
        'Design tokens at scale: how we keep four brands consistent across nine product surfaces.',
      topics: ['web'],
      address: { line1: '8 Mission St', city: 'San Francisco', country: 'US' },
      availableFrom: '2026-07-15',
      excitement: 4,
    }),
    make(3, 'accepted', 'Chen Wei', {
      fullName: 'Chen Wei',
      email: 'chen@example.com',
      track: 'product',
      isWorkshop: false,
      abstract:
        'Roadmaps that survive contact with customers — a product discovery playbook for B2B SaaS.',
      topics: ['data'],
      address: { line1: '88 Nanjing Rd', city: 'Shanghai', country: 'CN' },
      availableFrom: '2026-09-01',
      excitement: 5,
    }),
    make(4, 'submitted', 'Dana Levin', {
      fullName: 'Dana Levin',
      email: 'dana@example.com',
      track: 'engineering',
      isWorkshop: false,
      abstract:
        'Event-driven architecture in the small: pragmatic patterns for teams under ten engineers.',
      topics: ['cloud', 'web'],
      address: { line1: '3 Rothschild Blvd', city: 'Tel Aviv', country: 'IL' },
      availableFrom: '2026-08-20',
      excitement: 3,
    }),
    make(5, 'rejected', 'Eko Prasetyo', {
      fullName: 'Eko Prasetyo',
      email: 'eko@example.com',
      track: 'design',
      isWorkshop: true,
      seats: 12,
      feePerSeat: 0,
      projectedRevenue: 0,
      abstract:
        'Sketch-to-system: running collaborative whiteboard workshops that end with shipped UI.',
      topics: ['web'],
      address: { line1: 'Jl. Sudirman 45', city: 'Jakarta', country: 'ID' },
      availableFrom: '2026-07-01',
      excitement: 4,
    }),
  ];
}

let forms: MockForm[] = seedForms();
let submissions: FormSubmissionRow[] = seedSubmissions();

/** Test hook — fresh state per Vitest run. */
export function resetMockForms(): void {
  forms = seedForms();
  submissions = seedSubmissions();
}

// ---- helpers ----

function toRow(f: MockForm): FormRow {
  return clone({
    id: f.id,
    name: f.name,
    slug: f.slug,
    description: f.description,
    status: f.status,
    access: f.access,
    isTrashed: f.archived,
    currentVersionId: f.currentVersionId,
    currentVersionNumber: f.currentVersionNumber,
    hasUnpublishedChanges: f.hasUnpublishedChanges,
    opensAt: f.opensAt,
    closesAt: f.closesAt,
    maxSubmissions: f.maxSubmissions,
    submissionLimitPerUser: f.submissionLimitPerUser,
    pinnedColumns: f.pinnedColumns,
    displayMode: f.displayMode,
    allowRevisions: f.allowRevisions,
    submissionCount: submissions.filter((s) => s.formId === f.id && s.isCurrent).length,
    createdAt: f.createdAt,
    updatedAt: f.updatedAt,
  });
}

function toDetail(f: MockForm): FormDetail {
  return clone({ ...toRow(f), draftDefinition: f.draftDefinition });
}

function getForm(id: string): MockForm {
  const form = forms.find((f) => f.id === id);
  if (!form) throw new Error('Form not found.');
  return form;
}

function applyQuery(rows: FormRow[], query: ListQuery): { data: FormRow[]; total: number } {
  let out = rows;
  if (query.search) {
    const q = query.search.toLowerCase();
    out = out.filter(
      (r) => r.name.toLowerCase().includes(q) || (r.description ?? '').toLowerCase().includes(q),
    );
  }
  if (query.sort) {
    const { id, desc } = query.sort;
    out = [...out].sort((a, b) => {
      const av = String((a as unknown as Record<string, unknown>)[id] ?? '');
      const bv = String((b as unknown as Record<string, unknown>)[id] ?? '');
      return desc ? bv.localeCompare(av) : av.localeCompare(bv);
    });
  }
  const total = out.length;
  const start = query.page * query.pageSize;
  return { data: out.slice(start, start + query.pageSize), total };
}

function listRows(query: ListQuery): { data: FormRow[]; total: number } {
  const archivedView = query.statusView === 'trashed';
  const rows = forms.filter((f) => f.archived === archivedView).map(toRow);
  return applyQuery(rows, query);
}

function slugify(name: string): string {
  return (
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'form'
  );
}

// ---- the service ----

export const mockFormService: FormService = {
  list(query) {
    const { data, total } = listRows(query);
    return delay({ data, total, page: query.page });
  },

  getAt(query, index) {
    const { data, total } = listRows({ ...query, page: 0, pageSize: 10_000 });
    return delay({ form: data[index] ?? null, total });
  },

  get(id) {
    const form = forms.find((f) => f.id === id);
    return delay(form ? toDetail(form) : null);
  },

  create(payload: FormCreatePayload) {
    const id = newId('form');
    const doc: FormDocument = {
      schemaVersion: 1,
      pages: [
        {
          id: newId('pg'),
          title: '',
          sections: [{ id: newId('sec'), title: '', fields: [] }],
        },
      ],
    };
    const form: MockForm = {
      id,
      name: payload.name,
      slug: slugify(payload.name),
      description: payload.description ?? null,
      status: 'draft',
      access: payload.access ?? 'internal',
      currentVersionId: null,
      currentVersionNumber: null,
      hasUnpublishedChanges: true,
      opensAt: null,
      closesAt: null,
      maxSubmissions: null,
      submissionLimitPerUser: null,
      pinnedColumns: [],
      displayMode: 'paged',
      allowRevisions: false,
      submissionCount: 0,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      draftDefinition: doc,
      versionDocs: {},
      versionRows: [],
      archived: false,
    };
    forms = [form, ...forms];
    graphs[id] = seedGraph(id, false);
    return delay(toDetail(form));
  },

  update(id, payload: FormUpdatePayload) {
    const form = getForm(id);
    if (payload.name !== undefined) form.name = payload.name;
    if (payload.description !== undefined) form.description = payload.description;
    if (payload.access !== undefined) form.access = payload.access;
    if (payload.draftDefinition !== undefined) {
      form.draftDefinition = clone(payload.draftDefinition);
      form.hasUnpublishedChanges = true;
    }
    if (payload.opensAt !== undefined) form.opensAt = payload.opensAt;
    if (payload.closesAt !== undefined) form.closesAt = payload.closesAt;
    if (payload.maxSubmissions !== undefined) form.maxSubmissions = payload.maxSubmissions;
    if (payload.submissionLimitPerUser !== undefined) {
      form.submissionLimitPerUser = payload.submissionLimitPerUser;
    }
    if (payload.pinnedColumns !== undefined) form.pinnedColumns = payload.pinnedColumns;
    if (payload.displayMode !== undefined) form.displayMode = payload.displayMode;
    if (payload.allowRevisions !== undefined) form.allowRevisions = payload.allowRevisions;
    form.updatedAt = new Date().toISOString();
    return delay(toDetail(form));
  },

  publish(id) {
    const form = getForm(id);
    const problems = validateFormDoc(form.draftDefinition);
    if (problems.length) return Promise.reject(new FormPublishError(problems));
    const versionNumber = (form.currentVersionNumber ?? 0) + 1;
    const versionId = newId('ver');
    form.versionDocs[versionId] = clone(form.draftDefinition);
    form.versionRows = [
      {
        id: versionId,
        versionNumber,
        publishedBy: 'usr-demo',
        publishedByName: 'Demo User',
        createdAt: new Date().toISOString(),
      },
      ...form.versionRows,
    ];
    form.currentVersionId = versionId;
    form.currentVersionNumber = versionNumber;
    form.status = 'published';
    form.hasUnpublishedChanges = false;
    form.updatedAt = new Date().toISOString();
    return delay(toDetail(form));
  },

  unpublish(id) {
    const form = getForm(id);
    form.status = 'draft';
    form.updatedAt = new Date().toISOString();
    return delay(toDetail(form));
  },

  archive(id) {
    const form = getForm(id);
    form.archived = true;
    form.status = 'archived';
    form.updatedAt = new Date().toISOString();
    return delay(toRow(form));
  },

  restore(id) {
    const form = getForm(id);
    form.archived = false;
    form.status = form.currentVersionId ? 'published' : 'draft';
    form.updatedAt = new Date().toISOString();
    return delay(toRow(form));
  },

  remove(id) {
    forms = forms.filter((f) => f.id !== id);
    submissions = submissions.filter((s) => s.formId !== id);
    delete graphs[id];
    return delay(undefined);
  },

  async export(query, columns) {
    const { data } = listRows({ ...query, page: 0, pageSize: 10_000 });
    const rows = data.map((r) =>
      columns.map((c) => String((r as unknown as Record<string, unknown>)[c] ?? '')),
    );
    return toCsv(columns, rows);
  },

  versionDefinition(formId, versionId) {
    const form = getForm(formId);
    return delay(form.versionDocs[versionId] ? clone(form.versionDocs[versionId]) : null);
  },

  versions(formId, page, pageSize) {
    const form = getForm(formId);
    const start = page * pageSize;
    return delay({
      data: clone(form.versionRows.slice(start, start + pageSize)),
      total: form.versionRows.length,
      page,
    });
  },

  preview(formId) {
    const form = getForm(formId);
    return delay({
      formId,
      versionId: 'draft',
      versionNumber: form.currentVersionNumber ?? 0,
      name: form.name,
      description: form.description,
      definition: clone(form.draftDefinition),
      paged: form.displayMode === 'paged',
    } satisfies FormFillView);
  },

  fill(formId) {
    const form = getForm(formId);
    if (!form.currentVersionId || form.status !== 'published') return delay(null);
    return delay({
      formId,
      versionId: form.currentVersionId,
      versionNumber: form.currentVersionNumber ?? 1,
      name: form.name,
      description: form.description,
      definition: clone(form.versionDocs[form.currentVersionId]),
      paged: form.displayMode === 'paged',
    } satisfies FormFillView);
  },

  submit(formId, answers: FormAnswers) {
    const form = getForm(formId);
    if (!form.currentVersionId) return Promise.reject(new Error('Form is not published.'));
    const doc = form.versionDocs[form.currentVersionId];
    const errors = validateAll(doc, answers);
    if (Object.keys(errors).length) return Promise.reject(new FormSubmitError(errors));
    const graph = graphs[formId];
    const submitted = graph.statuses.find((s) => s.key === 'submitted') ?? graph.statuses[0];
    const id = newId('sub');
    const row: FormSubmissionRow = {
      id,
      formId,
      submissionGroupId: id,
      revisionNumber: 1,
      isCurrent: true,
      versionId: form.currentVersionId,
      versionNumber: form.currentVersionNumber ?? 1,
      statusId: submitted.id,
      statusKey: submitted.key,
      statusLabel: submitted.label,
      statusColor: submitted.color,
      userId: 'usr-demo',
      userName: 'Demo User',
      subjectType: null,
      subjectId: null,
      answers: visibleAnswers(doc, answers),
      submittedAt: new Date().toISOString(),
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      availableTransitionIds: graph.transitions
        .filter((t) => t.fromStatusId === submitted.id)
        .map((t) => t.id),
    };
    submissions = [row, ...submissions];
    return delay(clone(row));
  },

  submissions(formId, query) {
    // Lists default to the current revision of each group (R3) — one row/group.
    let rows = submissions.filter((s) => s.formId === formId && s.isCurrent);
    if (query.segment && query.segment !== 'all') {
      rows = rows.filter((s) => s.statusKey === query.segment);
    }
    if (query.search) {
      const q = query.search.toLowerCase();
      rows = rows.filter(
        (s) =>
          (s.userName ?? '').toLowerCase().includes(q) ||
          JSON.stringify(s.answers).toLowerCase().includes(q),
      );
    }
    const total = rows.length;
    const start = query.page * query.pageSize;
    return delay({ data: clone(rows.slice(start, start + query.pageSize)), total, page: query.page });
  },

  getSubmission(id) {
    return delay(clone(submissions.find((s) => s.id === id) ?? null));
  },

  submissionGraph(formId) {
    return delay(clone(graphs[formId] ?? { statuses: [], transitions: [] }));
  },

  transitionSubmission(id, transitionId) {
    const row = submissions.find((s) => s.id === id);
    if (!row) return Promise.reject(new Error('Submission not found.'));
    const graph = graphs[row.formId];
    const edge = graph.transitions.find((t) => t.id === transitionId);
    if (!edge || edge.fromStatusId !== row.statusId) {
      return Promise.reject(new Error('No transition from the current status.'));
    }
    const target = graph.statuses.find((s) => s.id === edge.toStatusId)!;
    row.statusId = target.id;
    row.statusKey = target.key;
    row.statusLabel = target.label;
    row.statusColor = target.color;
    row.updatedAt = new Date().toISOString();
    row.availableTransitionIds = graph.transitions
      .filter((t) => t.fromStatusId === target.id)
      .map((t) => t.id);
    return delay(clone(row));
  },

  revise(submissionId) {
    const prior = submissions.find((s) => s.id === submissionId);
    if (!prior) return Promise.reject(new Error('Submission not found.'));
    const form = getForm(prior.formId);
    if (!form.allowRevisions) {
      return Promise.reject(new Error('Revisions are not enabled for this form.'));
    }
    if (!prior.isCurrent) {
      return Promise.reject(new Error('Only the current revision can be revised.'));
    }
    const graph = graphs[prior.formId];
    const priorStatus = graph.statuses.find((s) => s.id === prior.statusId);
    if (priorStatus?.isActive) {
      return Promise.reject(new Error('This submission is still editable — edit it instead.'));
    }
    if (!form.currentVersionId) {
      return Promise.reject(new Error('The form has no published version to revise against.'));
    }
    const initial = graph.statuses.find((s) => s.isInitial) ?? graph.statuses[0];
    const maxRev = Math.max(
      ...submissions
        .filter((s) => s.submissionGroupId === prior.submissionGroupId)
        .map((s) => s.revisionNumber),
    );
    prior.isCurrent = false;
    const draft: FormSubmissionRow = {
      ...clone(prior),
      id: newId('sub'),
      submissionGroupId: prior.submissionGroupId,
      revisionNumber: maxRev + 1,
      isCurrent: true,
      versionId: form.currentVersionId,
      versionNumber: form.currentVersionNumber ?? prior.versionNumber,
      statusId: initial.id,
      statusKey: initial.key,
      statusLabel: initial.label,
      statusColor: initial.color,
      submittedAt: null,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      availableTransitionIds: graph.transitions
        .filter((t) => t.fromStatusId === initial.id)
        .map((t) => t.id),
    };
    submissions = [draft, ...submissions];
    return delay(clone(draft));
  },

  submissionRevisions(formId, groupId) {
    const chain = submissions
      .filter((s) => s.formId === formId && s.submissionGroupId === groupId)
      .sort((a, b) => b.revisionNumber - a.revisionNumber);
    return delay(clone(chain));
  },

  resubmitRevision(submissionId, answers: FormAnswers) {
    const row = submissions.find((s) => s.id === submissionId);
    if (!row) return Promise.reject(new Error('Submission not found.'));
    const graph = graphs[row.formId];
    const current = graph.statuses.find((s) => s.id === row.statusId);
    if (!row.isCurrent || !current?.isActive) {
      return Promise.reject(new Error('This revision is not open for editing.'));
    }
    const form = getForm(row.formId);
    const doc = form.versionDocs[row.versionId];
    if (doc) {
      const errors = validateAll(doc, answers);
      if (Object.keys(errors).length) return Promise.reject(new FormSubmitError(errors));
      row.answers = visibleAnswers(doc, answers);
    } else {
      row.answers = answers;
    }
    const edge = graph.transitions.find((t) => t.fromStatusId === row.statusId);
    const target = edge ? graph.statuses.find((s) => s.id === edge.toStatusId) : undefined;
    if (target) {
      row.statusId = target.id;
      row.statusKey = target.key;
      row.statusLabel = target.label;
      row.statusColor = target.color;
      row.availableTransitionIds = graph.transitions
        .filter((t) => t.fromStatusId === target.id)
        .map((t) => t.id);
    }
    row.submittedAt = new Date().toISOString();
    row.updatedAt = new Date().toISOString();
    return delay(clone(row));
  },

  async exportSubmissions(formId, query, columns) {
    const result = await this.submissions(formId, { ...query, page: 0, pageSize: 10_000 });
    const rows = result.data.map((s) =>
      columns.map((c) => {
        if (c.startsWith('answers.')) {
          const v = s.answers[c.slice('answers.'.length)];
          return typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v ?? '');
        }
        if (c === 'respondent') return s.userName ?? 'Anonymous';
        return String((s as unknown as Record<string, unknown>)[c] ?? '');
      }),
    );
    return toCsv(columns, rows);
  },
};
