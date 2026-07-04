import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MySubmissionsList } from './my-submissions-list';
import { MOCK_MY_SUBMISSIONS } from '@/services/portal-review-service.mock';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDateTime: (s: string) => s,
    formatDate: (s: string) => s,
    formatTime: (s: string) => s,
    timeZone: 'UTC',
  }),
}));

describe('MySubmissionsList', () => {
  it('shows lifecycle status, decision and feedback — never scores/reviews', () => {
    render(<MySubmissionsList submissions={MOCK_MY_SUBMISSIONS} onRevise={vi.fn()} />);
    // status labels (engine)
    expect(screen.getByText('Under review')).toBeInTheDocument();
    expect(screen.getByText('Awaiting revision')).toBeInTheDocument();
    // the decision badge ("Revisions requested") renders for the decided row
    expect(screen.getByText('Revisions requested')).toBeInTheDocument();
    // decision + feedback for the decided row
    expect(screen.getByTestId('submission-feedback')).toHaveTextContent(
      'Please clarify section 3.',
    );
    // NO raw scores anywhere in this surface
    expect(screen.queryByText(/score/i)).not.toBeInTheDocument();
  });

  it('shows Revise ONLY when canRevise is true', () => {
    render(<MySubmissionsList submissions={MOCK_MY_SUBMISSIONS} onRevise={vi.fn()} />);
    // Exactly one revisable row in the fixture.
    const reviseButtons = screen.getAllByTestId('revise-button');
    expect(reviseButtons).toHaveLength(1);
  });

  it('fires onRevise with the submission row', async () => {
    const onRevise = vi.fn();
    render(<MySubmissionsList submissions={MOCK_MY_SUBMISSIONS} onRevise={onRevise} />);
    await userEvent.click(screen.getByTestId('revise-button'));
    expect(onRevise).toHaveBeenCalledWith(
      expect.objectContaining({ groupId: 'grp-2', canRevise: true }),
    );
  });

  it('renders an empty state with no submissions', () => {
    render(<MySubmissionsList submissions={[]} onRevise={vi.fn()} />);
    expect(screen.getByText(/no submissions yet/i)).toBeInTheDocument();
  });

  it('shows the per-row event label when unfiltered (AC-06-25)', () => {
    render(
      <MySubmissionsList submissions={MOCK_MY_SUBMISSIONS} onRevise={vi.fn()} showContext />,
    );
    const labels = screen.getAllByTestId('row-context');
    expect(labels.map((n) => n.textContent)).toEqual(
      expect.arrayContaining(['Annual Summit', 'Spring Workshop']),
    );
  });

  it('hides the per-row event label when filtered to one event', () => {
    render(<MySubmissionsList submissions={MOCK_MY_SUBMISSIONS} onRevise={vi.fn()} />);
    expect(screen.queryByTestId('row-context')).not.toBeInTheDocument();
  });
});
