import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ReviewTwoPaneView } from './review-two-pane';
import { MOCK_TWO_PANE } from '@/services/portal-review-service.mock';
import type { FormAnswers } from '@/types/forms';
import type { ReviewSurfaceActions } from '@/types/portal-review';

// Mock the ONE FormRenderer so the test asserts WHICH pane mounts which mode
// (read submission ‖ fill review) + drives the submit/draft callbacks. The real
// renderer is covered by its own suite.
vi.mock('@/components/platform/form-renderer', () => ({
  FormRenderer: ({
    mode,
    onSubmit,
  }: {
    mode: string;
    onSubmit?: (a: FormAnswers) => void;
  }) => (
    <div data-testid={`renderer-${mode}`}>
      {onSubmit && (
        <button type="button" onClick={() => onSubmit({ score: 9 })}>
          renderer-submit
        </button>
      )}
    </div>
  ),
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDateTime: (s: string) => s, formatDate: (s: string) => s, formatTime: (s: string) => s, timeZone: 'UTC' }),
}));

function makeActions(): ReviewSurfaceActions {
  return {
    getTwoPane: vi.fn(),
    saveDraft: vi.fn().mockResolvedValue({ submissionId: 'd', answers: {} }),
    submitReview: vi.fn().mockResolvedValue({}),
  };
}

describe('ReviewTwoPaneView (shared grade view)', () => {
  it('renders the submission pane (read) and the review form pane (fill)', () => {
    render(<ReviewTwoPaneView data={MOCK_TWO_PANE} actions={makeActions()} />);
    expect(screen.getByTestId('submission-pane')).toBeInTheDocument();
    expect(screen.getByTestId('review-pane')).toBeInTheDocument();
    // The submission is read-only; the review form is interactive (fill).
    expect(screen.getByTestId('renderer-read')).toBeInTheDocument();
    expect(screen.getByTestId('renderer-fill')).toBeInTheDocument();
  });

  it('Save draft fires the saveDraft action', async () => {
    const actions = makeActions();
    render(<ReviewTwoPaneView data={MOCK_TWO_PANE} actions={actions} />);
    await userEvent.click(screen.getByRole('button', { name: /save draft/i }));
    await waitFor(() => expect(actions.saveDraft).toHaveBeenCalledWith('asg-1', {}));
  });

  it('Submit (via the renderer) fires submitReview with the answers', async () => {
    const actions = makeActions();
    const onSubmitted = vi.fn();
    render(
      <ReviewTwoPaneView data={MOCK_TWO_PANE} actions={actions} onSubmitted={onSubmitted} />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'renderer-submit' }));
    await waitFor(() =>
      expect(actions.submitReview).toHaveBeenCalledWith('asg-1', { score: 9 }),
    );
    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
  });

  it('seeds the review answers from THIS reviewer\'s own draft only (isolation)', async () => {
    const actions = makeActions();
    const withDraft = {
      ...MOCK_TWO_PANE,
      reviewDraft: { submissionId: 'rsub-mine', answers: { score: 3 } },
    };
    render(<ReviewTwoPaneView data={withDraft} actions={actions} />);
    await userEvent.click(screen.getByRole('button', { name: /save draft/i }));
    // The save carries the seeded draft answers — never another reviewer's data
    // (the payload only ever contains this assignment's own draft).
    await waitFor(() =>
      expect(actions.saveDraft).toHaveBeenCalledWith('asg-1', { score: 3 }),
    );
  });
});
