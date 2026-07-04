import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { DecisionPanel } from './decision-panel';
import { MOCK_DECISIONS } from '@/services/portal-review-service.mock';
import type { DecisionItem, DecisionSurfaceActions } from '@/types/portal-review';

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function makeActions(): DecisionSurfaceActions {
  return { decide: vi.fn().mockResolvedValue(MOCK_DECISIONS[0]) };
}

describe('DecisionPanel (shared decision panel)', () => {
  it('shows the live average and a Ready badge once required reviews are met', () => {
    render(<DecisionPanel item={MOCK_DECISIONS[0]} actions={makeActions()} />);
    expect(within(screen.getByTestId('average-score')).getByText('7.50')).toBeInTheDocument();
    expect(screen.getByTestId('ready-badge')).toHaveTextContent('2 / 2');
    expect(screen.getByTestId('ready-badge')).toHaveTextContent('Ready');
  });

  it('does NOT show Ready before requiredReviewCount, but Decide is still enabled (early)', async () => {
    const partial: DecisionItem = {
      ...MOCK_DECISIONS[0],
      completedCount: 1,
      ready: false,
      averageScore: 8,
    };
    render(<DecisionPanel item={partial} actions={makeActions()} />);
    expect(screen.getByTestId('ready-badge')).not.toHaveTextContent('Ready');
    // Early decide is allowed — the Decide button is present + enabled.
    const decide = screen.getByRole('button', { name: /^decide$/i });
    expect(decide).toBeEnabled();
  });

  it('records a decision + feedback with the right payload shape', async () => {
    const actions = makeActions();
    render(<DecisionPanel item={MOCK_DECISIONS[0]} actions={actions} />);
    await userEvent.click(screen.getByRole('button', { name: /^decide$/i }));

    // Pick a decision (SearchSelect) — open + choose "Accept".
    await userEvent.click(screen.getByRole('combobox', { name: /decision/i }));
    await userEvent.click(await screen.findByRole('option', { name: 'Accept' }));

    await userEvent.type(screen.getByPlaceholderText('Optional'), 'Great work');
    await userEvent.click(screen.getByRole('button', { name: /record decision/i }));

    await waitFor(() =>
      expect(actions.decide).toHaveBeenCalledWith('grp-9', 'ACCEPTED', 'Great work'),
    );
  });

  it('expands individual reviews (decider-only)', async () => {
    render(<DecisionPanel item={MOCK_DECISIONS[0]} actions={makeActions()} />);
    expect(screen.queryByTestId('individual-reviews')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /reviews/i }));
    expect(screen.getByTestId('individual-reviews')).toBeInTheDocument();
  });
});
