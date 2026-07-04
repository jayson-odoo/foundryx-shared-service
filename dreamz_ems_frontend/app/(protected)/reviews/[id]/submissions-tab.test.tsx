import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { SubmissionsTab } from './submissions-tab';
import type { ReviewAdminSubmission } from '@/types/review';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDateTime: (s: string) => s,
    formatDate: (s: string) => s,
    formatTime: (s: string) => s,
    timeZone: 'UTC',
  }),
}));

const SUBMISSIONS: ReviewAdminSubmission[] = [
  {
    groupId: 'grp-1',
    submissionId: 'sub-1',
    revisionNumber: 1,
    title: 'Towards efficient review',
    statusId: 'st-accepted',
    statusLabel: 'Accepted',
    statusColor: '#22c55e',
    author: { kind: 'profile', id: 'prof-1', name: 'Ada Lovelace' },
    submittedAt: '2026-06-21T00:00:00Z',
    createdAt: '2026-06-21T00:00:00Z',
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
      decidedAt: '2026-06-21T00:00:00Z',
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
    submittedAt: null,
    createdAt: '2026-06-21T00:00:00Z',
    reviews: [],
    averageScore: null,
    requiredReviewCount: 2,
    completedCount: 0,
    ready: false,
    decision: null,
  },
];

describe('SubmissionsTab', () => {
  it('renders each group with status, author, average and decision', () => {
    render(<SubmissionsTab submissions={SUBMISSIONS} loading={false} error={null} />);
    const rows = screen.getAllByTestId('admin-submission-row');
    expect(rows).toHaveLength(2);

    // Group 1 — status + author + average + decision verdict.
    const first = within(rows[0]);
    expect(first.getByText('Towards efficient review')).toBeInTheDocument();
    expect(first.getByText(/Ada Lovelace/)).toBeInTheDocument();
    // status badge label (engine) + decision chip both read "Accepted".
    expect(first.getAllByText('Accepted').length).toBeGreaterThanOrEqual(1);
    expect(first.getByTestId('avg-chip')).toHaveTextContent('Avg 8');
    expect(first.getByTestId('ready-chip')).toHaveTextContent('1/2 reviews');
    expect(first.getByTestId('decision-chip')).toHaveTextContent('Accepted');

    // Group 2 — no decision, no average.
    const second = within(rows[1]);
    expect(second.getByTestId('avg-chip')).toHaveTextContent('Avg —');
    expect(second.getByTestId('decision-chip')).toHaveTextContent('No decision');
  });

  it('reveals the nested per-reviewer reviews when a row is expanded', async () => {
    render(<SubmissionsTab submissions={SUBMISSIONS} loading={false} error={null} />);
    // Collapsed by default — no review rows yet.
    expect(screen.queryByTestId('admin-review-row')).not.toBeInTheDocument();

    const rows = screen.getAllByTestId('admin-submission-row');
    await userEvent.click(within(rows[0]).getByRole('button'));

    const reviewRows = screen.getAllByTestId('admin-review-row');
    expect(reviewRows).toHaveLength(2);
    // The completed reviewer carries the score; the pending one shows a dash.
    expect(within(reviewRows[0]).getByText('Grace Hopper')).toBeInTheDocument();
    expect(within(reviewRows[0]).getByText('Completed')).toBeInTheDocument();
    expect(within(reviewRows[0]).getByText('8')).toBeInTheDocument();
    expect(within(reviewRows[1]).getByText('Alan Turing')).toBeInTheDocument();
    expect(within(reviewRows[1]).getByText('Pending')).toBeInTheDocument();
  });

  it('renders the empty state with no submissions', () => {
    render(<SubmissionsTab submissions={[]} loading={false} error={null} />);
    expect(screen.getByTestId('submissions-empty')).toHaveTextContent('No submissions yet.');
  });

  it('renders the loading state', () => {
    const { container } = render(
      <SubmissionsTab submissions={[]} loading error={null} />,
    );
    expect(container.querySelector('.animate-spin')).toBeInTheDocument();
  });
});
