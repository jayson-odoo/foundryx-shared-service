/**
 * Contact panel - Lifecycle move (plan 25, F15/F14 review findings). The
 * "Move to" picker offers ONLY the fireable moves the backend returns
 * (foolproof-UI - never a stale/invalid option), is gated by
 * `contacts.manage` (F16), and a 409 renders the STRUCTURED machine message
 * (`detail.message`), not the generic HTTP text (F14, AC-CDM-37).
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from '@/lib/toast';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { ApiError } from '@/lib/api-client';
import type { ContactLifecycleSummary, LifecycleMove } from '@/types/omnichannel';
import { LifecycleMove as LifecycleMoveSection } from './lifecycle-move';

let can: (key: string) => boolean = () => true;
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (key: string) => can(key) }),
}));

vi.mock('@/lib/toast', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

let moves: LifecycleMove[] = [];
const lifecycleMoves = vi.fn<(contactId: string) => Promise<LifecycleMove[]>>(async () => moves);
vi.mock('@/services/conversation-service', () => ({
  conversationService: { lifecycleMoves: (contactId: string) => lifecycleMoves(contactId) },
}));

const LIFECYCLE: ContactLifecycleSummary = {
  statusId: 'st-2',
  key: 'hot_lead',
  label: 'Hot Lead',
  color: '#FF5A00',
  isWon: false,
  isLost: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  moves = [
    { edgeId: 'edge-1', toStatusId: 'st-3', label: 'Customer' },
    { edgeId: 'edge-2', toStatusId: 'st-4', label: 'Lost' },
  ];
  can = () => true;
});

describe('LifecycleMove', () => {
  it('shows only the fireable moves the backend returns', async () => {
    const user = userEvent.setup();
    render(<LifecycleMoveSection contactId="cnt-001" lifecycle={LIFECYCLE} onMove={vi.fn()} />);

    await waitFor(() => expect(lifecycleMoves).toHaveBeenCalledWith('cnt-001'));
    await user.click(screen.getByRole('combobox', { name: 'Move to' }));
    expect(await screen.findByRole('option', { name: 'Customer' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Lost' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Won' })).not.toBeInTheDocument();
  });

  it('says "no further moves" on a terminal/won stage with zero fireable edges', async () => {
    moves = [];
    render(<LifecycleMoveSection contactId="cnt-001" lifecycle={LIFECYCLE} onMove={vi.fn()} />);
    expect(await screen.findByText('No further moves from this stage.')).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Move to' })).not.toBeInTheDocument();
  });

  it('hides the picker entirely without contacts.manage (F16)', async () => {
    can = () => false;
    render(<LifecycleMoveSection contactId="cnt-001" lifecycle={LIFECYCLE} onMove={vi.fn()} />);
    await waitFor(() => expect(lifecycleMoves).toHaveBeenCalled());
    expect(screen.queryByRole('combobox', { name: 'Move to' })).not.toBeInTheDocument();
  });

  it('renders the structured 409 machine message, not the generic HTTP text (F14)', async () => {
    const onMove = vi.fn().mockRejectedValue(
      new ApiError('Request failed', 409, null, {
        code: 'lifecycle_move_not_allowed',
        message: 'No move from Customer to Hot Lead.',
      }),
    );
    const user = userEvent.setup();
    render(<LifecycleMoveSection contactId="cnt-001" lifecycle={LIFECYCLE} onMove={onMove} />);

    await user.click(await screen.findByRole('combobox', { name: 'Move to' }));
    await user.click(await screen.findByRole('option', { name: 'Customer' }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith('No move from Customer to Hot Lead.'),
    );
    expect(toast.error).not.toHaveBeenCalledWith('Request failed');
  });

  it('F5: a rejected (409) move refetches the fireable-moves list', async () => {
    const onMove = vi.fn().mockRejectedValue(
      new ApiError('Request failed', 409, null, {
        code: 'lifecycle_move_not_allowed',
        message: 'No move from Customer to Hot Lead.',
      }),
    );
    const user = userEvent.setup();
    render(<LifecycleMoveSection contactId="cnt-001" lifecycle={LIFECYCLE} onMove={onMove} />);

    await waitFor(() => expect(lifecycleMoves).toHaveBeenCalledTimes(1));
    await user.click(await screen.findByRole('combobox', { name: 'Move to' }));
    await user.click(await screen.findByRole('option', { name: 'Customer' }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    // The stale fireable-list that offered the now-rejected move gets
    // refetched - the server is the source of truth on what's ACTUALLY
    // fireable, and a 409 means our cached list disagreed with it.
    await waitFor(() => expect(lifecycleMoves).toHaveBeenCalledTimes(2));
  });

  it('F5: a changeSignal change refetches even when the stage key is unchanged', async () => {
    const { rerender } = render(
      <LifecycleMoveSection contactId="cnt-001" lifecycle={LIFECYCLE} onMove={vi.fn()} changeSignal="a" />,
    );
    await waitFor(() => expect(lifecycleMoves).toHaveBeenCalledTimes(1));

    // Same contact, same stage key - only the fingerprint of OTHER
    // condition-relevant fields (priority/assignee/etc) changed.
    rerender(
      <LifecycleMoveSection contactId="cnt-001" lifecycle={LIFECYCLE} onMove={vi.fn()} changeSignal="b" />,
    );
    await waitFor(() => expect(lifecycleMoves).toHaveBeenCalledTimes(2));
  });
});
