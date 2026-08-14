/**
 * PHASE 1 MOCK - in-memory Business Requirement service (Phase B-i slice 2).
 *
 * Frontend-first scaffolding: drives every UI state (loading/error/success) with
 * no backend. The shipped app binds `.real` (see business-requirement-service.ts);
 * this mock is retained ONLY for Vitest. Do NOT ship this behind a "done" slice.
 */
import type { Idea } from '@/types/ideation';
import type { FormDocument } from '@/types/forms';
import type {
  BrTemplateVersion,
  BusinessRequirement,
  BusinessRequirementDetail,
  BusinessRequirementStatus,
} from '@/types/business-requirement';
import type { BrListFilter, BusinessRequirementService } from './business-requirement-service';

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

function seedBr(id: string, title: string, status: BusinessRequirementStatus): BusinessRequirementDetail {
  return {
    id,
    productId: 'prod-1',
    productName: 'Sorento CRM',
    status,
    statusLabel: status.charAt(0).toUpperCase() + status.slice(1),
    statusColor: status === 'ready' ? 'green' : 'gray',
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
  };
}

const store = new Map<string, BusinessRequirementDetail>([
  ['br-1', seedBr('br-1', 'Order export to Excel', 'draft')],
  ['br-2', seedBr('br-2', 'Bulk invoice download', 'ready')],
]);

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
  },
];

function toRow(d: BusinessRequirementDetail): BusinessRequirement {
  const row = { ...d } as Partial<BusinessRequirementDetail>;
  delete row.answers;
  delete row.templateDoc;
  return row as BusinessRequirement;
}

export const mockBusinessRequirementService: BusinessRequirementService = {
  async list(params?: BrListFilter) {
    let rows = Array.from(store.values());
    if (params?.filter === 'archived') rows = rows.filter((r) => r.status === 'archived');
    else if (params?.filter !== 'all') rows = rows.filter((r) => r.status !== 'archived');
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
};
