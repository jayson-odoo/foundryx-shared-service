/**
 * PHASE 1 MOCK - in-memory Business Requirement service (Phase B-i slice 2).
 *
 * Frontend-first scaffolding: drives every UI state (loading/error/success) with
 * no backend. The shipped app binds `.real` (see business-requirement-service.ts);
 * this mock is retained ONLY for Vitest. Do NOT ship this behind a "done" slice.
 *
 * Send-to-build seeds (plan ideation-br-send-to-build S0): br-1 blocked
 * (missing fields), br-2 sendable, br-3 already sent (issue 1402 + 5 trace events).
 */
import { ApiError } from '@/lib/api-client';
import type { Idea } from '@/types/ideation';
import type { FormDocument } from '@/types/forms';
import type {
  BrTemplateVersion,
  BuildEvent,
  BuildInfo,
  BuildKey,
  BuildKeyMinted,
  BusinessRequirement,
  BusinessRequirementDetail,
  BusinessRequirementStatus,
} from '@/types/business-requirement';
import type {
  BrListFilter,
  BrTemplateStatus,
  BusinessRequirementService,
} from './business-requirement-service';

const MOCK_TEMPLATE_DOC: FormDocument = {
  schemaVersion: 1,
  pages: [
    {
      id: 'page-br',
      title: 'Business Requirement',
      sections: [
        {
          id: 'sec-br',
          title: 'Requirement',
          fields: [
            { id: 'f1', type: 'textarea', key: 'problem_statement', label: 'Problem statement', required: true },
            { id: 'f2', type: 'textarea', key: 'business_goal', label: 'Business goal', required: true },
            { id: 'f3', type: 'textarea', key: 'stakeholders', label: 'Stakeholders' },
            { id: 'f4', type: 'textarea', key: 'success_metric', label: 'Success metric', required: true },
            { id: 'f5', type: 'textarea', key: 'scope', label: 'Scope' },
            { id: 'f6', type: 'textarea', key: 'constraints', label: 'Constraints' },
          ],
        },
      ],
    },
  ],
} as FormDocument;

const MOCK_REPO = 'jayson-odoo/sorento-crm';
const BLOCKED_REASON = 'Missing: Success metric, Constraints';

function noBuild(over: Partial<BuildInfo> = {}): BuildInfo {
  return {
    canSend: false,
    sendEdgeAvailable: true,
    blockers: [BLOCKED_REASON],
    repo: MOCK_REPO,
    issueUrl: null,
    issueNumber: null,
    state: 'none',
    sentAt: null,
    sentBy: null,
    stage: null,
    prUrl: null,
    handtestUrl: null,
    events: [],
    ...over,
  };
}

function ev(seq: number, over: Partial<BuildEvent>): BuildEvent {
  return {
    id: `ev-${seq}`,
    seq,
    kind: 'crew',
    stage: 'Plan',
    message: '',
    prUrl: null,
    handtestUrl: null,
    status: 'in_progress',
    statusMoved: false,
    actorName: null,
    createdAt: `2026-09-29T15:${String(40 + seq).padStart(2, '0')}:00Z`,
    ...over,
  };
}

const SENT_EVENTS: BuildEvent[] = [
  ev(1, { kind: 'sent', stage: 'Sent', message: 'Sent to build', status: null, actorName: 'Jayson Teh' }),
  ev(2, { stage: 'Plan', message: 'Plan approved, lane started' }),
  ev(3, { stage: 'Mock', message: 'Mock ready for review' }),
  ev(4, {
    stage: 'PR+CI',
    message: 'Draft PR opened, CI running',
    prUrl: 'https://github.com/jayson-odoo/sorento-crm/pull/1410',
  }),
  ev(5, {
    stage: 'Review',
    message: 'Ready for hand test',
    handtestUrl: 'http://localhost:3103',
  }),
];

function sentBuild(): BuildInfo {
  const last = SENT_EVENTS[SENT_EVENTS.length - 1];
  return {
    canSend: false,
    sendEdgeAvailable: false,
    blockers: [],
    repo: MOCK_REPO,
    issueUrl: `https://github.com/${MOCK_REPO}/issues/1402`,
    issueNumber: 1402,
    state: 'sent',
    sentAt: SENT_EVENTS[0].createdAt,
    sentBy: { id: 'u-1', name: 'Jayson Teh' },
    stage: last.stage,
    prUrl: 'https://github.com/jayson-odoo/sorento-crm/pull/1410',
    handtestUrl: 'http://localhost:3103',
    events: SENT_EVENTS,
  };
}

function seedBr(
  id: string,
  title: string,
  status: BusinessRequirementStatus,
  build: BuildInfo = noBuild(),
): BusinessRequirementDetail {
  return {
    id,
    productId: 'prod-1',
    productName: 'Sorento CRM',
    status,
    statusLabel: status === 'sent_to_build' ? 'Sent to build' : status.charAt(0).toUpperCase() + status.slice(1),
    statusColor: status === 'ready' ? 'green' : status === 'sent_to_build' ? 'violet' : 'gray',
    templateKey: 'business_requirement',
    templateVersion: 1,
    title,
    ideaCount: 1,
    createdAt: '2026-07-20T10:00:00Z',
    updatedAt: '2026-07-20T10:00:00Z',
    answers: {
      problem_statement: 'CS cannot export orders to Excel.',
      business_goal: 'Cut manual reporting time.',
      success_metric: '50% fewer support tickets.',
    },
    templateDoc: MOCK_TEMPLATE_DOC,
    build,
  };
}

const store = new Map<string, BusinessRequirementDetail>([
  ['br-1', seedBr('br-1', 'Order export to Excel', 'draft')],
  ['br-2', seedBr('br-2', 'Bulk invoice download', 'ready', noBuild({ canSend: true, blockers: [] }))],
  ['br-3', seedBr('br-3', 'Quote approval by WhatsApp', 'sent_to_build', sentBuild())],
]);

const keys: BuildKeyMinted[] = [];
let keySeq = 0;
function toKey(k: BuildKeyMinted): BuildKey {
  return {
    id: k.id,
    name: k.name,
    keyPrefix: k.keyPrefix,
    createdAt: k.createdAt,
    lastUsedAt: k.lastUsedAt,
  };
}

const MOCK_IDEAS: Idea[] = [
  {
    id: 'idea-1',
    productId: 'prod-1',
    productName: 'Sorento CRM',
    status: 'triaged',
    problem: 'Export orders to Excel',
    rawText: '',
    source: 'whatsapp',
    submitterName: 'Aisha',
    upvotes: 3,
    downvotes: 0,
    myVote: null,
    priority: 0,
    attachments: [],
    createdAt: '2026-07-19T09:00:00Z',
    isTest: false,
  },
];

function toRow(d: BusinessRequirementDetail): BusinessRequirement {
  const row = { ...d } as Partial<BusinessRequirementDetail>;
  delete row.answers;
  delete row.templateDoc;
  delete row.build;
  return row as BusinessRequirement;
}

export const mockBusinessRequirementService: BusinessRequirementService = {
  async list(params?: BrListFilter) {
    let rows = Array.from(store.values());
    if (params?.filter === 'archived') rows = rows.filter((r) => r.status === 'archived');
    else if (params?.filter !== 'all') rows = rows.filter((r) => r.status !== 'archived');
    if (!params?.includeTest) rows = rows.filter((r) => !r.isTest);
    if (params?.search) {
      const q = params.search.toLowerCase();
      rows = rows.filter((r) => r.title.toLowerCase().includes(q));
    }
    return rows.map(toRow);
  },

  async get(id: string) {
    const br = store.get(id);
    if (!br) throw new Error('Business requirement not found.');
    return { ...br };
  },

  async create(input) {
    const id = `br-${store.size + 1}`;
    const detail = seedBr(id, input.title ?? 'Untitled BR', 'draft');
    detail.answers = input.answers ?? {};
    detail.ideaCount = input.ideaIds?.length ?? 0;
    store.set(id, detail);
    return { ...detail };
  },

  async update(id, input) {
    const br = store.get(id);
    if (!br) throw new Error('Business requirement not found.');
    if (input.title !== undefined) br.title = input.title;
    if (input.answers !== undefined) br.answers = input.answers;
    store.set(id, br);
    return { ...br };
  },

  async setStatus(id, status) {
    const br = store.get(id);
    if (!br) throw new Error('Business requirement not found.');
    br.status = status;
    br.statusLabel = status.charAt(0).toUpperCase() + status.slice(1);
    store.set(id, br);
    return { ...br };
  },

  async statusGraph() {
    return { entityType: 'ideation_business_requirement', source: 'platform', statuses: [], transitions: [] };
  },

  async listIdeas() {
    return MOCK_IDEAS;
  },

  async listForIdea() {
    return Array.from(store.values());
  },

  async linkIdeas() {
    return MOCK_IDEAS;
  },

  async unlinkIdea() {
    return [];
  },

  async listVersions(): Promise<BrTemplateVersion[]> {
    return [{ version: 1, isStamped: true, isActive: true, createdAt: '2026-07-20T10:00:00Z' }];
  },

  async remove(id) {
    store.delete(id);
  },

  async templateStatus(): Promise<BrTemplateStatus> {
    return { active: true };
  },

  async sendToBuild(id) {
    const br = store.get(id);
    if (!br) throw new Error('Business requirement not found.');
    if (br.build.state === 'sent') return { ...br };
    if (!br.build.canSend) {
      throw new ApiError('Unprocessable', 422, null, {
        message: br.build.blockers[0] ?? 'This requirement cannot be sent yet.',
        blockers: br.build.blockers,
      });
    }
    const number = 1403 + Array.from(store.values()).filter((b) => b.build.state === 'sent').length;
    const sentAt = new Date().toISOString();
    br.status = 'sent_to_build';
    br.statusLabel = 'Sent to build';
    br.statusColor = 'violet';
    br.build = {
      ...br.build,
      canSend: false,
      sendEdgeAvailable: false,
      state: 'sent',
      issueNumber: number,
      issueUrl: `https://github.com/${MOCK_REPO}/issues/${number}`,
      sentAt,
      sentBy: { id: 'u-1', name: 'Jayson Teh' },
      stage: 'Sent',
      events: [
        ev(1, {
          kind: 'sent',
          stage: 'Sent',
          message: 'Sent to build',
          status: null,
          actorName: 'Jayson Teh',
          createdAt: sentAt,
        }),
      ],
    };
    store.set(id, br);
    return { ...br };
  },

  async getBuild(id) {
    const br = store.get(id);
    if (!br) throw new Error('Business requirement not found.');
    return { ...br.build };
  },

  async listBuildKeys() {
    return keys.map(toKey);
  },

  async mintBuildKey(name) {
    keySeq += 1;
    const plaintext = `fxb_live_${String(keySeq).padStart(4, '0')}abcdefabcdefabcdefabcdefabcd`;
    const minted: BuildKeyMinted = {
      id: `key-${keySeq}`,
      name,
      keyPrefix: plaintext.slice(9, 17),
      createdAt: new Date().toISOString(),
      lastUsedAt: null,
      plaintext,
    };
    keys.push(minted);
    return { ...minted };
  },

  async revokeBuildKey(id) {
    const at = keys.findIndex((k) => k.id === id);
    if (at >= 0) keys.splice(at, 1);
  },
};
