import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MySubmissionsClient } from './my-submissions-client';
import type { FormAnswers } from '@/types/forms';
import type { MySubmission, SubmitOption } from '@/types/portal-review';

// ── Chrome + terminology stubbed so the client renders in isolation. ─────────
vi.mock('../portal-page-shell', () => ({
  PortalPageShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock('@/hooks/use-portal-terminology', () => ({
  usePortalTerminology: () => ({
    label: (k: string) => (k === 'submission' ? 'Submission' : k),
    labelPlural: (k: string) => (k === 'submission' ? 'Submissions' : k),
  }),
}));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDateTime: (s: string) => s,
    formatDate: (s: string) => s,
    formatTime: (s: string) => s,
    timeZone: 'UTC',
  }),
}));

// The global event-filter provider — unfiltered (null) for these tests.
vi.mock('@/providers/portal-filter-provider', () => ({
  usePortalFilter: () => ({ activeContextKey: null, setActiveContextKey: vi.fn() }),
}));

// Capture the answers FormRenderer is mounted with (revise prefill assertion).
const rendererSeen = vi.hoisted(() => ({ answers: null as FormAnswers | null }));
vi.mock('@/components/platform/form-renderer', () => ({
  FormRenderer: ({ answers }: { answers: FormAnswers }) => {
    rendererSeen.answers = answers;
    return <div data-testid="form-renderer" />;
  },
}));

// ── Review surface hooks: controllable stores. ───────────────────────────────
const stores = vi.hoisted(() => ({
  submissions: [] as MySubmission[],
  submitOptions: [] as SubmitOption[],
  actions: {
    submitFormView: vi.fn(),
    submit: vi.fn(),
    revise: vi.fn(),
    resubmit: vi.fn(),
    submissionDetail: vi.fn(),
  },
}));

vi.mock('@/hooks/use-portal-review', () => ({
  usePortalSubmissions: () => ({
    data: stores.submissions,
    loading: false,
    error: null,
    reload: vi.fn(),
  }),
  usePortalSubmitOptions: () => ({
    data: stores.submitOptions,
    loading: false,
    error: null,
    reload: vi.fn(),
  }),
  usePortalSubmissionActions: () => stores.actions,
}));

const OPEN_OPTION: SubmitOption = {
  configId: 'cfg-1',
  name: 'Paper review',
  submissionFormId: 'form-1',
  contextId: null,
  contextLabel: null,
  windowState: 'open',
  windowStart: null,
  windowEnd: null,
  canSubmitNow: true,
};

const CLOSED_OPTION: SubmitOption = {
  configId: 'cfg-2',
  name: 'Late call',
  submissionFormId: 'form-2',
  contextId: null,
  contextLabel: null,
  windowState: 'closed',
  windowStart: null,
  windowEnd: '2026-01-01T00:00:00Z',
  canSubmitNow: false,
};

const REVISABLE: MySubmission = {
  groupId: 'grp-2',
  submissionId: 'sub-2',
  reviewConfigurationId: 'cfg-1',
  reviewConfigurationName: 'Paper review',
  contextId: null,
  contextLabel: null,
  formId: 'form-1',
  title: 'Needs work',
  revisionNumber: 2,
  statusId: 'st-rev',
  statusLabel: 'Awaiting revision',
  statusColor: '#D97706',
  decision: 'REVISIONS',
  feedbackText: 'Clarify section 3.',
  decidedAt: '2026-06-21T10:00:00Z',
  canRevise: true,
  submittedAt: '2026-06-20T10:00:00Z',
  createdAt: '2026-06-19T10:00:00Z',
};

describe('MySubmissionsClient', () => {
  beforeEach(() => {
    stores.submissions = [];
    stores.submitOptions = [];
    rendererSeen.answers = null;
    Object.values(stores.actions).forEach((fn) => fn.mockReset());
  });

  it('renders a Submit action for an eligible config with NO existing submissions (AC-06-03)', () => {
    stores.submissions = []; // zero prior submissions
    stores.submitOptions = [OPEN_OPTION];
    render(<MySubmissionsClient />);

    const btn = screen.getByRole('button', { name: /Paper review/ });
    expect(btn).toBeEnabled();
  });

  it('disables Submit for a closed window with a status line, not how-to copy', () => {
    stores.submitOptions = [CLOSED_OPTION];
    render(<MySubmissionsClient />);

    const btn = screen.getByRole('button', { name: /Late call/ });
    expect(btn).toBeDisabled();
    expect(btn.textContent).toMatch(/Submissions closed/);
  });

  it('opens the submit dialog and renders the fill form for an eligible config', async () => {
    stores.submitOptions = [OPEN_OPTION];
    stores.actions.submitFormView.mockResolvedValue({
      state: 'open',
      configId: 'cfg-1',
      form: {
        formId: 'form-1',
        versionId: 'ver-1',
        name: 'Abstract',
        description: null,
        definition: { schemaVersion: 1, pages: [] },
        paged: false,
      },
    });
    render(<MySubmissionsClient />);

    await userEvent.click(screen.getByRole('button', { name: /Paper review/ }));
    await waitFor(() => expect(screen.getByTestId('form-renderer')).toBeInTheDocument());
    expect(stores.actions.submitFormView).toHaveBeenCalledWith('cfg-1');
  });

  it('Revise prefills the FormRenderer with the prior revision answers (AC-06-09)', async () => {
    stores.submissions = [REVISABLE];
    stores.submitOptions = [OPEN_OPTION];
    stores.actions.submissionDetail.mockResolvedValue({
      ...REVISABLE,
      answers: { title: 'Prior title', body: 'Prior body' },
      versionId: 'ver-1',
    });
    stores.actions.revise.mockResolvedValue({
      submissionId: 'sub-new',
      groupId: 'grp-2',
      revisionNumber: 3,
    });
    stores.actions.submitFormView.mockResolvedValue({
      state: 'open',
      configId: 'cfg-1',
      form: {
        formId: 'form-1',
        versionId: 'ver-1',
        name: 'Abstract',
        description: null,
        definition: { schemaVersion: 1, pages: [] },
        paged: false,
      },
    });
    render(<MySubmissionsClient />);

    await userEvent.click(screen.getByTestId('revise-button'));
    await waitFor(() => expect(screen.getByTestId('form-renderer')).toBeInTheDocument());

    expect(stores.actions.submissionDetail).toHaveBeenCalledWith('grp-2');
    expect(stores.actions.revise).toHaveBeenCalledWith('grp-2');
    expect(rendererSeen.answers).toEqual({ title: 'Prior title', body: 'Prior body' });
  });
});
