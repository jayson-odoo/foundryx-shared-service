import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ReviewTwoPaneView } from './review-two-pane';
import { DecisionPanel } from './decision-panel';
import { MOCK_DECISIONS, MOCK_TWO_PANE } from '@/services/portal-review-service.mock';
import type {
  DecisionSurfaceActions,
  ReviewSurfaceActions,
} from '@/types/portal-review';

vi.mock('@/components/platform/form-renderer', () => ({
  FormRenderer: ({ mode }: { mode: string }) => <div data-testid={`renderer-${mode}`} />,
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDateTime: (s: string) => s, formatDate: (s: string) => s, formatTime: (s: string) => s, timeZone: 'UTC' }),
}));

/**
 * Reuse-don't-rebuild (AC-06-46/47): the SAME shared components render for BOTH
 * the staff world and the portal world. The only difference is the
 * service-bound `actions` the page supplies — there is NO "profile"/"user"
 * branching inside the component.
 */
describe('shared review components serve both worlds', () => {
  it('ReviewTwoPaneView renders identically for staff vs portal actions', () => {
    const staffActions: ReviewSurfaceActions = {
      getTwoPane: vi.fn(),
      saveDraft: vi.fn().mockResolvedValue({ submissionId: 's', answers: {} }),
      submitReview: vi.fn(),
    };
    const portalActions: ReviewSurfaceActions = {
      getTwoPane: vi.fn(),
      saveDraft: vi.fn().mockResolvedValue({ submissionId: 'p', answers: {} }),
      submitReview: vi.fn(),
    };

    const staff = render(<ReviewTwoPaneView data={MOCK_TWO_PANE} actions={staffActions} />);
    expect(screen.getByTestId('submission-pane')).toBeInTheDocument();
    expect(screen.getByTestId('review-pane')).toBeInTheDocument();
    staff.unmount();

    render(<ReviewTwoPaneView data={MOCK_TWO_PANE} actions={portalActions} />);
    expect(screen.getByTestId('submission-pane')).toBeInTheDocument();
    expect(screen.getByTestId('review-pane')).toBeInTheDocument();
  });

  it('the component invokes whichever world\'s service it was given', async () => {
    const portalActions: ReviewSurfaceActions = {
      getTwoPane: vi.fn(),
      saveDraft: vi.fn().mockResolvedValue({ submissionId: 'p', answers: {} }),
      submitReview: vi.fn(),
    };
    render(<ReviewTwoPaneView data={MOCK_TWO_PANE} actions={portalActions} />);
    await userEvent.click(screen.getByRole('button', { name: /save draft/i }));
    await waitFor(() => expect(portalActions.saveDraft).toHaveBeenCalled());
  });

  it('DecisionPanel decide() calls the supplied world\'s service', async () => {
    const staffDecide: DecisionSurfaceActions = {
      decide: vi.fn().mockResolvedValue(MOCK_DECISIONS[0]),
    };
    render(<DecisionPanel item={MOCK_DECISIONS[0]} actions={staffDecide} />);
    await userEvent.click(screen.getByRole('button', { name: /^decide$/i }));
    await userEvent.click(screen.getByRole('combobox', { name: /decision/i }));
    await userEvent.click(await screen.findByRole('option', { name: 'Reject' }));
    await userEvent.click(screen.getByRole('button', { name: /record decision/i }));
    await waitFor(() =>
      expect(staffDecide.decide).toHaveBeenCalledWith('grp-9', 'REJECTED', null),
    );
  });
});
