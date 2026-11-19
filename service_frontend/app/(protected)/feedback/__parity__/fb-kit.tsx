/**
 * Test kit for the feedback pages (ideas list, board, idea record, comments,
 * business requirements, embed connections): fixed records, a stand-in for
 * `lib/api-client` that answers reads from them and records every write
 * (method, path, body), and a wrapper that renders a page with the Foundryx
 * UIUX switch on or off. Used by the switch-off parity snapshots and by the
 * tests that compare what both looks send.
 */
import type { ReactNode } from 'react';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import type { Idea, IdeaComment } from '@/types/ideation';
import type { BusinessRequirement } from '@/types/business-requirement';

export const T0 = '2026-03-04T05:06:07Z';

export const ALL_PERMISSIONS = [
  'ideation.ideas.read',
  'ideation.ideas.comment',
  'ideation.triage.manage',
  'ideation.business_requirements.read',
  'ideation.business_requirements.manage',
  'ideation.business_requirements.promote',
  'ideation.business_requirements.send_to_build',
];

export const PRODUCT = { id: 'prod-1', name: 'Sorento CRM', kind: 'software' };

export const IDEA: Idea = {
  id: 'idea-1',
  productId: 'prod-1',
  productName: 'Sorento CRM',
  status: 'captured',
  problem: 'Export orders to Excel',
  rawText: 'raw',
  source: 'whatsapp',
  submitterName: 'Jayson',
  upvotes: 3,
  downvotes: 1,
  myVote: null,
  priority: 1,
  attachments: [],
  createdAt: T0,
  isTest: false,
  statusId: 'idea-status-captured',
  statusLabel: 'New',
  statusColor: 'blue',
  statusIsArchived: false,
  transitions: [
    { id: 'idea-tr-1', label: 'Triage', toStatusId: 'idea-status-triaged', toStatusLabel: 'Triaged' },
  ],
  advanceTransitionId: 'idea-tr-1',
  rank: 1,
  mergedIntoId: null,
  mergedInto: null,
  mergedCount: 0,
} as Idea;

export const IDEA_2: Idea = {
  ...IDEA,
  id: 'idea-2',
  problem: 'Dark mode for the dashboard',
  submitterName: 'Aisha',
  upvotes: 1,
  rank: 2,
  statusId: 'idea-status-triaged',
  status: 'triaged',
  statusLabel: 'Triaged',
  statusColor: 'amber',
  transitions: [
    { id: 'idea-tr-2', label: 'Back', toStatusId: 'idea-status-captured', toStatusLabel: 'New' },
  ],
  advanceTransitionId: null,
} as Idea;

export const IDEAS: Idea[] = [IDEA, IDEA_2];

export const BOARD = {
  columns: [
    { statusId: 'idea-status-captured', key: 'captured', title: 'New', color: 'blue', ideas: [IDEA] },
    { statusId: 'idea-status-triaged', key: 'triaged', title: 'Triaged', color: 'amber', ideas: [IDEA_2] },
    { statusId: 'idea-status-linked', key: 'linked', title: 'Linked to BR', color: 'violet', ideas: [] },
  ],
};

export const COMMENT: IdeaComment = {
  id: 'c-1',
  ideaId: 'idea-1',
  parentId: null,
  authorName: 'Demo Admin',
  authorKind: 'user',
  body: 'Looks good to me',
  isDeleted: false,
  isMine: true,
  canEdit: true,
  canDelete: true,
  createdAt: T0,
  editedAt: null,
};

export const BR: BusinessRequirement = {
  id: 'br-1',
  productId: 'prod-1',
  productName: 'Sorento CRM',
  status: 'draft',
  statusLabel: 'Draft',
  statusColor: 'gray',
  templateKey: 'default',
  templateVersion: 1,
  title: 'Order export to Excel',
  ideaCount: 1,
  createdAt: T0,
  updatedAt: T0,
};

export const CONNECTION_ROW = {
  connection_id: 'sorento-feedback',
  tenant_id: 't-1',
  allowed_origins: ['https://app.example.com'],
  product_id: null,
  is_active: true,
  has_secret: true,
  created_at: T0,
  updated_at: T0,
};

export interface RecordedWrite {
  method: string;
  path: string;
  body: unknown;
}

/** Writes seen by the stand-in api client, in order. */
export const writes: RecordedWrite[] = [];

/** Answers a read from the fixtures above. */
function read(path: string): unknown {
  const p = path.split('?')[0];
  if (p === '/products') return { items: [PRODUCT], total: 1, page: 0, pageSize: 200 };
  if (p === '/ideation/ideas') return IDEAS;
  if (p === '/ideation/ideas/board') return BOARD;
  const ideaHit = IDEAS.find((i) => p === `/ideation/ideas/${i.id}`);
  if (ideaHit) return ideaHit;
  if (p.endsWith('/comments')) return [COMMENT];
  if (p === '/ideation/embed-connections') return [CONNECTION_ROW];
  if (p === '/ideation/business-requirements') return [BR];
  if (p === '/ideation/business-requirements/template-status') return { active: true };
  return null;
}

/** What a write answers with (the created or updated record). */
function answer(method: string, path: string, body: unknown): unknown {
  const b = (body ?? {}) as Record<string, unknown>;
  if (path === '/ideation/ideas' && method === 'POST') return { ...IDEA, id: 'idea-new', ...b };
  if (path === '/ideation/ideas/idea-1' && method === 'PATCH') return { ...IDEA, ...b };
  if (path.endsWith('/status')) return { ...IDEA, statusLabel: 'Triaged', status: 'triaged' };
  if (path.endsWith('/vote')) return { ...IDEA, upvotes: IDEA.upvotes + 1, myVote: 'up' };
  if (path.endsWith('/comments') && method === 'POST') return { ...COMMENT, id: 'c-new', body: b.body };
  if (path.includes('/comments/') && method === 'PATCH') return { ...COMMENT, body: b.body };
  if (path === '/ideation/ideas/reorder') return IDEAS;
  if (path === '/ideation/business-requirements' && method === 'POST') return { ...BR, id: 'br-new', ...b };
  if (path === '/ideation/embed-connections' && method === 'POST')
    return { ...CONNECTION_ROW, connection_id: b.connection_id };
  if (path.endsWith('/rotate')) return CONNECTION_ROW;
  return null;
}

/** The `apiFetch` stand-in: reads from fixtures, records every write. */
export async function fakeApiFetch(path: string, init: RequestInit = {}): Promise<unknown> {
  const method = (init.method ?? 'GET').toUpperCase();
  if (method === 'GET') return read(path);
  const body = typeof init.body === 'string' ? JSON.parse(init.body) : (init.body ?? null);
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
