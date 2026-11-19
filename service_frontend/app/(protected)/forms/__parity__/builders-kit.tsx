/**
 * Test kit for the workflows and forms pages: fixed records, a stand-in for
 * `lib/api-client` that answers reads from them and records every write
 * (method, path, body), and a wrapper that renders a page with the Foundryx
 * UIUX switch on or off. Used by the switch-off parity snapshots and by the
 * tests that compare what both looks send.
 */
import type { ReactNode } from 'react';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import type {
  FormDetail,
  FormDocument,
  FormFillView,
  FormRow,
  FormSubmissionRow,
} from '@/types/forms';
import type { Workflow, WorkflowListItem } from '@/types/workflows';

export const T0 = '2026-03-04T05:06:07Z';

export const FORM_DOC: FormDocument = {
  schemaVersion: 1,
  pages: [
    {
      id: 'p1',
      title: 'Details',
      sections: [
        {
          id: 's1',
          title: 'About you',
          fields: [
            { id: 'f1', type: 'text', key: 'fullName', label: 'Full name', required: true },
            { id: 'f2', type: 'date', key: 'startDate', label: 'Start date' },
            { id: 'f3', type: 'integer', key: 'headcount', label: 'Headcount', number: { min: 0, max: 50 } },
            { id: 'f4', type: 'number', key: 'budget', label: 'Budget', number: { decimals: 2, min: 0 } },
            {
              id: 'f5',
              type: 'select',
              key: 'plan',
              label: 'Plan',
              options: {
                kind: 'static',
                items: [
                  { value: 'basic', label: 'Basic' },
                  { value: 'pro', label: 'Pro' },
                ],
              },
            },
            { id: 'f6', type: 'yesno', key: 'agree', label: 'Agree' },
            { id: 'f7', type: 'datetime', key: 'callAt', label: 'Call at' },
            { id: 'f8', type: 'file', key: 'attachment', label: 'Attachment' },
          ],
        },
      ],
    },
  ],
};

export const FORM_ROW: FormRow = {
  id: 'f-1',
  name: 'Site visit',
  slug: 'site-visit',
  description: 'Before a visit',
  status: 'published',
  access: 'internal',
  isTrashed: false,
  currentVersionId: 'v-1',
  currentVersionNumber: 1,
  hasUnpublishedChanges: true,
  opensAt: null,
  closesAt: null,
  maxSubmissions: null,
  submissionLimitPerUser: null,
  pinnedColumns: [],
  displayMode: 'single',
  allowRevisions: false,
  submissionCount: 3,
  createdAt: T0,
  updatedAt: T0,
};

export const FORM: FormDetail = { ...FORM_ROW, draftDefinition: FORM_DOC };

export const FILL_VIEW: FormFillView = {
  formId: FORM.id,
  versionId: 'v-1',
  versionNumber: 1,
  name: FORM.name,
  description: FORM.description,
  definition: FORM_DOC,
  paged: false,
};

export const SUBMISSION: FormSubmissionRow = {
  id: 's-1',
  formId: FORM.id,
  submissionGroupId: 's-1',
  revisionNumber: 1,
  isCurrent: true,
  versionId: 'v-1',
  versionNumber: 1,
  statusId: 'st-1',
  statusKey: 'submitted',
  statusLabel: 'Submitted',
  statusColor: 'green',
  userId: 'u-9',
  userName: 'Jane Doe',
  subjectType: null,
  subjectId: null,
  answers: { fullName: 'Jane Doe', startDate: '2026-03-09', headcount: 4, plan: 'pro', agree: true },
  submittedAt: T0,
  createdAt: T0,
  updatedAt: T0,
  availableTransitionIds: [],
};

export const WORKFLOW_ROW: WorkflowListItem = {
  id: 'w-1',
  name: 'Reply to new chats',
  description: 'Greets new contacts',
  isActive: true,
  isTrashed: false,
  triggerType: 'omnichannel.message_received',
  triggerLabel: 'Incoming message',
  currentVersionNumber: 2,
  hasUnpublishedChanges: true,
  lastRunAt: T0,
  lastRunStatus: 'success',
  updatedAt: T0,
};

export const WORKFLOW: Workflow = {
  ...WORKFLOW_ROW,
  draftDefinition: {
    schemaVersion: 1,
    nodes: [
      {
        id: 'trigger-1',
        kind: 'trigger',
        type: 'omnichannel.message_received',
        config: { channelId: 'chn-1' },
        position: { x: 0, y: 0 },
      },
    ],
    edges: [],
  },
  currentVersionId: 'wv-2',
  currentVersion: null,
  createdByName: 'Demo Admin',
  createdAt: T0,
};

export const ALL_PERMISSIONS = [
  'workflows.read',
  'workflows.manage',
  'workflows.code',
  'workflows.http',
  'forms.read',
  'forms.manage',
  'submissions.read',
  'submissions.manage',
];

export interface RecordedWrite {
  method: string;
  path: string;
  body: unknown;
}

/** Writes seen by the stand-in api client, in order. */
export const writes: RecordedWrite[] = [];

/** Reads the same stand-in answers from, replaceable per test. */
export const state = { form: FORM, workflow: WORKFLOW, submission: SUBMISSION };

function list<T>(data: T[]) {
  return { data, total: data.length, page: 0, pageSize: 50 };
}

function read(path: string): unknown {
  const p = path.split('?')[0];
  if (p === '/workflows') return list([WORKFLOW_ROW]);
  if (p === '/workflows/at') return { workflow: WORKFLOW_ROW, total: 1 };
  if (p === '/workflows/metadata') return { entities: [], codeRunnerAvailable: false };
  if (p === '/workflows/template-options') return [];
  if (p === `/workflows/${WORKFLOW.id}`) return state.workflow;
  if (p === '/forms') return list([FORM_ROW]);
  if (p === '/forms/at') return { form: FORM_ROW, total: 1 };
  if (p === `/forms/${FORM.id}`) return state.form;
  if (p === `/forms/${FORM.id}/fill`) return FILL_VIEW;
  if (p === `/forms/${FORM.id}/versions/v-1`) return { id: 'v-1', versionNumber: 1, definition: FORM_DOC };
  if (p === `/forms/${FORM.id}/graph`) return { statuses: [], transitions: [] };
  if (p === `/forms/${FORM.id}/submissions`) return list([state.submission]);
  if (p === `/submissions/${SUBMISSION.id}`) return state.submission;
  return null;
}

function answer(method: string, path: string, body: unknown): unknown {
  const b = (body ?? {}) as Record<string, unknown>;
  if (path === '/workflows' && method === 'POST') return { ...WORKFLOW, id: 'w-new', ...b };
  if (path.startsWith('/workflows/') && method === 'PATCH') return { ...WORKFLOW, ...b };
  if (path.startsWith('/workflows/')) return WORKFLOW;
  if (path === '/forms' && method === 'POST') return { ...FORM, id: 'f-new', ...b };
  if (path.startsWith('/forms/') && method === 'PATCH') return { ...FORM, ...b };
  if (path.startsWith('/forms/') && path.endsWith('/submissions')) return SUBMISSION;
  if (path.startsWith('/submissions/')) return SUBMISSION;
  if (path.startsWith('/forms/')) return FORM;
  return null;
}

/** A multipart body as plain data, so both looks can be compared. */
function plain(body: unknown): unknown {
  if (typeof body === 'string') return JSON.parse(body);
  if (typeof FormData !== 'undefined' && body instanceof FormData) {
    return Array.from(body.entries()).map(([k, v]) => [k, typeof v === 'string' ? v : `file:${(v as File).name}`]);
  }
  return body ?? null;
}

/** The `apiFetch` stand-in: reads from fixtures, records every write. */
export async function fakeApiFetch(path: string, init: RequestInit = {}): Promise<unknown> {
  const method = (init.method ?? 'GET').toUpperCase();
  if (method === 'GET') return read(path);
  const body = plain(init.body);
  writes.push({ method, path, body });
  return answer(method, path, body);
}

/** Renders `children` with the switch on (`fx`) or off. */
export function Look({ fx, children }: { fx: boolean; children: ReactNode }) {
  return (
    <FxProvider initial={fx} initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}
