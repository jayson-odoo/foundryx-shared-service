/**
 * Mock portal review-surface service (plan sprint-4/06 slice 2) — drives the
 * Vitest surface tests with no backend. Deterministic fixtures cover the
 * shapes the shared components assert against.
 */
import type { FormDocument } from '@/types/forms';
import type {
  DecisionItem,
  MyReview,
  MySubmission,
  ReviewTwoPane,
  SubmissionDetail,
  SubmitFormState,
  SubmitOption,
} from '@/types/portal-review';
import type { PortalReviewService } from './portal-review-service';

const RUBRIC_DOC: FormDocument = {
  schemaVersion: 1,
  pages: [
    {
      id: 'p1',
      sections: [
        {
          id: 's1',
          title: 'Score',
          fields: [
            { id: 'f1', key: 'score', type: 'number', label: 'Score', required: true },
          ],
        },
      ],
    },
  ],
} as unknown as FormDocument;

const SUBMISSION_DOC: FormDocument = {
  schemaVersion: 1,
  pages: [
    {
      id: 'p1',
      sections: [
        {
          id: 's1',
          title: 'Abstract',
          fields: [
            { id: 'f1', key: 'title', type: 'text', label: 'Title', required: true },
          ],
        },
      ],
    },
  ],
} as unknown as FormDocument;

export const MOCK_MY_SUBMISSIONS: MySubmission[] = [
  {
    groupId: 'grp-1',
    submissionId: 'sub-1',
    reviewConfigurationId: 'cfg-1',
    reviewConfigurationName: 'Paper review',
    contextId: 'evt-summit',
    contextLabel: 'Annual Summit',
    formId: 'form-1',
    title: 'My abstract',
    revisionNumber: 1,
    statusId: 'st-rev',
    statusLabel: 'Under review',
    statusColor: '#2563EB',
    decision: null,
    feedbackText: null,
    decidedAt: null,
    canRevise: false,
    submittedAt: '2026-06-20T10:00:00Z',
    createdAt: '2026-06-19T10:00:00Z',
  },
  {
    groupId: 'grp-2',
    submissionId: 'sub-2',
    reviewConfigurationId: 'cfg-2',
    reviewConfigurationName: 'Workshop review',
    contextId: 'evt-workshop',
    contextLabel: 'Spring Workshop',
    formId: 'form-2',
    title: 'Needs work',
    revisionNumber: 2,
    statusId: 'st-revisions',
    statusLabel: 'Awaiting revision',
    statusColor: '#D97706',
    decision: 'REVISIONS',
    feedbackText: 'Please clarify section 3.',
    decidedAt: '2026-06-21T10:00:00Z',
    canRevise: true,
    submittedAt: '2026-06-20T10:00:00Z',
    createdAt: '2026-06-19T10:00:00Z',
  },
];

export const MOCK_MY_REVIEWS: MyReview[] = [
  {
    assignmentId: 'asg-1',
    reviewConfigurationId: 'cfg-1',
    reviewConfigurationName: 'Paper review',
    contextId: 'evt-summit',
    contextLabel: 'Annual Summit',
    groupId: 'grp-9',
    revisionNumber: 1,
    status: 'PENDING',
    dueAt: '2026-06-30T23:59:00Z',
    assignedAt: '2026-06-20T10:00:00Z',
    completedAt: null,
    title: 'A paper to grade',
  },
];

export const MOCK_TWO_PANE: ReviewTwoPane = {
  assignmentId: 'asg-1',
  status: 'PENDING',
  reviewConfigurationId: 'cfg-1',
  reviewConfigurationName: 'Paper review',
  submission: {
    id: 'sub-9',
    formId: 'form-1',
    versionId: 'ver-1',
    answers: { title: 'A paper to grade' },
    definition: SUBMISSION_DOC,
    revisionNumber: 1,
  },
  reviewForm: {
    formId: 'rev-form-1',
    versionId: 'rev-ver-1',
    versionNumber: 1,
    name: 'Rubric',
    description: null,
    definition: RUBRIC_DOC,
    paged: false,
  },
  reviewDraft: null,
};

export const MOCK_DECISIONS: DecisionItem[] = [
  {
    groupId: 'grp-9',
    submissionId: 'sub-9',
    reviewConfigurationId: 'cfg-1',
    reviewConfigurationName: 'Paper review',
    contextId: 'evt-summit',
    contextLabel: 'Annual Summit',
    title: 'A paper to decide',
    revisionNumber: 1,
    statusId: 'st-rev',
    statusLabel: 'Under review',
    statusColor: '#2563EB',
    averageScore: 7.5,
    completedCount: 2,
    requiredReviewCount: 2,
    ready: true,
    decision: null,
    feedbackText: null,
    reviews: [
      {
        assignmentId: 'asg-1',
        reviewSubmissionId: 'rsub-1',
        answers: { score: 8, comment: 'Strong' },
        score: 8,
        completedAt: '2026-06-21T10:00:00Z',
      },
      {
        assignmentId: 'asg-2',
        reviewSubmissionId: 'rsub-2',
        answers: { score: 7, comment: 'Good' },
        score: 7,
        completedAt: '2026-06-21T11:00:00Z',
      },
    ],
    submittedAt: '2026-06-20T10:00:00Z',
    createdAt: '2026-06-19T10:00:00Z',
  },
];

export const MOCK_SUBMIT_OPTIONS: SubmitOption[] = [
  {
    configId: 'cfg-1',
    name: 'Paper review',
    contextId: 'evt-summit',
    contextLabel: 'Annual Summit',
    submissionFormId: 'form-1',
    windowState: 'open',
    windowStart: null,
    windowEnd: '2026-12-31T23:59:00Z',
    canSubmitNow: true,
  },
  {
    configId: 'cfg-closed',
    name: 'Closed call',
    contextId: 'evt-workshop',
    contextLabel: 'Spring Workshop',
    submissionFormId: 'form-2',
    windowState: 'closed',
    windowStart: null,
    windowEnd: '2026-01-01T00:00:00Z',
    canSubmitNow: false,
  },
];

export const mockPortalReviewService: PortalReviewService = {
  async mySubmissions(_token, contextId) {
    if (!contextId) return MOCK_MY_SUBMISSIONS;
    return MOCK_MY_SUBMISSIONS.filter((s) => s.contextId === contextId);
  },
  async submitOptions(_token, contextId): Promise<SubmitOption[]> {
    if (!contextId) return MOCK_SUBMIT_OPTIONS;
    return MOCK_SUBMIT_OPTIONS.filter((o) => o.contextId === contextId);
  },
  async submissionDetail(groupId): Promise<SubmissionDetail> {
    const base =
      MOCK_MY_SUBMISSIONS.find((s) => s.groupId === groupId) ?? MOCK_MY_SUBMISSIONS[0];
    return { ...base, answers: { title: 'Prior answer' }, versionId: 'ver-1' };
  },
  async submitFormView(configId): Promise<SubmitFormState> {
    return {
      state: 'open',
      configId,
      form: {
        formId: 'form-1',
        versionId: 'ver-1',
        name: 'Abstract form',
        description: null,
        definition: SUBMISSION_DOC,
        paged: false,
      },
    };
  },
  async submit() {
    return MOCK_MY_SUBMISSIONS[0];
  },
  async revise(groupId) {
    return { submissionId: 'sub-new', groupId, revisionNumber: 3 };
  },
  async resubmit() {
    return MOCK_MY_SUBMISSIONS[0];
  },
  async myReviews(_token, contextId) {
    if (!contextId) return MOCK_MY_REVIEWS;
    return MOCK_MY_REVIEWS.filter((r) => r.contextId === contextId);
  },
  async reviewTwoPane() {
    return MOCK_TWO_PANE;
  },
  async saveReviewDraft(_assignmentId, answers) {
    return { submissionId: 'rsub-draft', answers };
  },
  async submitReview() {
    return {};
  },
  async decisions(_token, contextId) {
    if (!contextId) return MOCK_DECISIONS;
    return MOCK_DECISIONS.filter((d) => d.contextId === contextId);
  },
  async decide(groupId, decision, feedback) {
    return { ...MOCK_DECISIONS[0], groupId, decision, feedbackText: feedback };
  },
};
