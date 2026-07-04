/**
 * Mock Review-config service — in-memory store for frontend-first iteration and
 * the offline `npm run dev` UI tuning (loading/error/success states). The real
 * implementation swaps in at the service boundary (one line).
 */
import type { ListQuery, ListResult } from '@/types/resource';
import type {
  ReviewAdminSubmission,
  ReviewConfig,
  ReviewConfigCreateInput,
  ReviewConfigMeta,
  ReviewConfigUpdateInput,
  ReviewRole,
  ReviewRoleInput,
} from '@/types/review';
import type { ReviewConfigService } from './review-config-service';

let seq = 100;
const id = () => `mock-${++seq}`;

const now = '2026-06-21T00:00:00Z';

const store: ReviewConfig[] = [
  {
    id: 'rc-1',
    name: 'Paper peer review',
    formId: 'form-abstract',
    reviewFormId: 'form-rubric',
    requiredReviewCount: 2,
    scoreFieldKey: 'overall',
    windowStart: '2026-07-01T00:00:00Z',
    windowEnd: '2026-07-31T00:00:00Z',
    reviewStartStatusId: 'st-review',
    revisionsStatusId: 'st-revisions',
    acceptedStatusId: 'st-accepted',
    rejectedStatusId: 'st-rejected',
    isActive: true,
    roles: [
      {
        id: 'role-author',
        reviewConfigurationId: 'rc-1',
        key: 'author',
        label: 'Author',
        canSubmit: true,
        canReview: false,
        canDecide: false,
        actorSource: 'PERSONA',
        actorIdentityKind: 'profile',
        boundPersonaId: 'persona-participant',
        boundStaffRoleId: null,
        conditionsJson: null,
        sortOrder: 0,
        actors: [],
      },
      {
        id: 'role-reviewer',
        reviewConfigurationId: 'rc-1',
        key: 'reviewer',
        label: 'Reviewer',
        canSubmit: false,
        canReview: true,
        canDecide: false,
        actorSource: 'RULE',
        actorIdentityKind: 'profile',
        boundPersonaId: null,
        boundStaffRoleId: null,
        conditionsJson: null,
        sortOrder: 1,
        actors: [],
      },
    ],
    createdAt: now,
    updatedAt: now,
  },
];

const META: ReviewConfigMeta = {
  submissionStatuses: [
    { id: 'st-draft', label: 'Draft', color: '#94a3b8' },
    { id: 'st-submitted', label: 'Submitted', color: '#3b82f6' },
    { id: 'st-review', label: 'In review', color: '#f59e0b' },
    { id: 'st-revisions', label: 'Revisions requested', color: '#a855f7' },
    { id: 'st-accepted', label: 'Accepted', color: '#22c55e' },
    { id: 'st-rejected', label: 'Rejected', color: '#ef4444' },
  ],
  numericFields: [
    { key: 'overall', label: 'Overall score' },
    { key: 'originality', label: 'Originality' },
  ],
  submissionFacts: [
    {
      key: 'answers.track',
      label: 'Track',
      type: 'enum',
      source: 'submission',
      sourceLabel: 'Submission answers',
      options: [
        { value: 'ai', label: 'AI' },
        { value: 'systems', label: 'Systems' },
      ],
    },
    {
      key: 'answers.isStudent',
      label: 'Student paper',
      type: 'boolean',
      source: 'submission',
      sourceLabel: 'Submission answers',
    },
  ],
};

const ADMIN_SUBMISSIONS: Record<string, ReviewAdminSubmission[]> = {
  'rc-1': [
    {
      groupId: 'grp-1',
      submissionId: 'sub-1',
      revisionNumber: 1,
      title: 'Towards efficient review',
      statusId: 'st-accepted',
      statusLabel: 'Accepted',
      statusColor: '#22c55e',
      author: { kind: 'profile', id: 'prof-1', name: 'Ada Lovelace' },
      submittedAt: now,
      createdAt: now,
      reviews: [
        {
          assignmentId: 'asg-1',
          reviewerKind: 'profile',
          reviewerId: 'prof-9',
          reviewerName: 'Grace Hopper',
          status: 'COMPLETED',
          score: 8,
        },
        {
          assignmentId: 'asg-2',
          reviewerKind: 'profile',
          reviewerId: 'prof-10',
          reviewerName: 'Alan Turing',
          status: 'PENDING',
          score: null,
        },
      ],
      averageScore: 8,
      requiredReviewCount: 2,
      completedCount: 1,
      ready: false,
      decision: {
        decision: 'ACCEPTED',
        feedbackText: 'Strong contribution; minor typos.',
        deciderKind: 'profile',
        deciderId: 'prof-3',
        deciderName: 'Edsger Dijkstra',
        decidedAt: now,
      },
    },
    {
      groupId: 'grp-2',
      submissionId: 'sub-2',
      revisionNumber: 1,
      title: 'A note on scheduling',
      statusId: 'st-review',
      statusLabel: 'In review',
      statusColor: '#f59e0b',
      author: { kind: 'profile', id: 'prof-2', name: 'Katherine Johnson' },
      submittedAt: now,
      createdAt: now,
      reviews: [],
      averageScore: null,
      requiredReviewCount: 2,
      completedCount: 0,
      ready: false,
      decision: null,
    },
  ],
};

function roleFromInput(r: ReviewRoleInput, cfgId: string): ReviewRole {
  return {
    id: id(),
    reviewConfigurationId: cfgId,
    key: r.key,
    label: r.label,
    canSubmit: r.canSubmit,
    canReview: r.canReview,
    canDecide: r.canDecide,
    actorSource: r.actorSource,
    actorIdentityKind: r.actorIdentityKind,
    boundPersonaId: r.boundPersonaId ?? null,
    boundStaffRoleId: r.boundStaffRoleId ?? null,
    conditionsJson: r.conditionsJson ?? null,
    sortOrder: r.sortOrder ?? 0,
    actors: (r.actors ?? []).map((a) => ({
      id: id(),
      actorKind: a.actorKind,
      actorId: a.actorId,
      conditionsJson: a.conditionsJson ?? null,
      sortOrder: a.sortOrder ?? 0,
    })),
  };
}

export const mockReviewConfigService: ReviewConfigService = {
  async list(query: ListQuery): Promise<ListResult<ReviewConfig>> {
    const search = (query.search ?? '').trim().toLowerCase();
    const rows = search
      ? store.filter((r) => r.name.toLowerCase().includes(search))
      : store;
    return { data: rows, total: rows.length, page: query.page };
  },
  async get(cfgId: string): Promise<ReviewConfig | null> {
    return store.find((r) => r.id === cfgId) ?? null;
  },
  async create(payload: ReviewConfigCreateInput): Promise<ReviewConfig> {
    const cfgId = id();
    const cfg: ReviewConfig = {
      id: cfgId,
      name: payload.name,
      formId: payload.formId,
      reviewFormId: payload.reviewFormId,
      requiredReviewCount: payload.requiredReviewCount ?? 1,
      scoreFieldKey: payload.scoreFieldKey ?? null,
      windowStart: payload.windowStart ?? null,
      windowEnd: payload.windowEnd ?? null,
      reviewStartStatusId: payload.reviewStartStatusId ?? null,
      revisionsStatusId: payload.revisionsStatusId ?? null,
      acceptedStatusId: payload.acceptedStatusId ?? null,
      rejectedStatusId: payload.rejectedStatusId ?? null,
      isActive: payload.isActive ?? true,
      roles: (payload.roles ?? []).map((r) => roleFromInput(r, cfgId)),
      createdAt: now,
      updatedAt: now,
    };
    store.unshift(cfg);
    return cfg;
  },
  async update(cfgId: string, payload: ReviewConfigUpdateInput): Promise<ReviewConfig> {
    const cfg = store.find((r) => r.id === cfgId);
    if (!cfg) throw new Error('Not found.');
    Object.assign(cfg, {
      name: payload.name ?? cfg.name,
      formId: payload.formId ?? cfg.formId,
      reviewFormId: payload.reviewFormId ?? cfg.reviewFormId,
      requiredReviewCount: payload.requiredReviewCount ?? cfg.requiredReviewCount,
      scoreFieldKey: payload.scoreFieldKey !== undefined ? payload.scoreFieldKey : cfg.scoreFieldKey,
      windowStart: payload.windowStart !== undefined ? payload.windowStart : cfg.windowStart,
      windowEnd: payload.windowEnd !== undefined ? payload.windowEnd : cfg.windowEnd,
      reviewStartStatusId:
        payload.reviewStartStatusId !== undefined ? payload.reviewStartStatusId : cfg.reviewStartStatusId,
      revisionsStatusId:
        payload.revisionsStatusId !== undefined ? payload.revisionsStatusId : cfg.revisionsStatusId,
      acceptedStatusId:
        payload.acceptedStatusId !== undefined ? payload.acceptedStatusId : cfg.acceptedStatusId,
      rejectedStatusId:
        payload.rejectedStatusId !== undefined ? payload.rejectedStatusId : cfg.rejectedStatusId,
      isActive: payload.isActive ?? cfg.isActive,
      updatedAt: now,
    });
    if (payload.roles) cfg.roles = payload.roles.map((r) => roleFromInput(r, cfgId));
    return cfg;
  },
  async remove(cfgId: string): Promise<void> {
    const i = store.findIndex((r) => r.id === cfgId);
    if (i >= 0) store.splice(i, 1);
  },
  async meta(): Promise<ReviewConfigMeta> {
    return META;
  },
  async adminSubmissions(configId: string): Promise<ReviewAdminSubmission[]> {
    return ADMIN_SUBMISSIONS[configId] ?? [];
  },
};
