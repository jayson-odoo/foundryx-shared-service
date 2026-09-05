/**
 * AC-IVE-20/22/48 - the view rail's per-view manage control: own view (by
 * REAL session user id, not a hardcoded id) always offers Rename/Delete;
 * someone else's non-shared view only does with `inbox_views.manage`.
 *
 * Review round 2 (findings 2/3/4) - the delete flow itself: it is a DEFERRED
 * action (no confirm dialog), deleting the currently-selected view must fall
 * back to All (not leave `filters.viewId` pointing at a deleted row), and
 * starting a second delete while one is still counting down must settle the
 * first toast rather than let it silently hijack the second's Cancel.
 */
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ConversationFilters } from '@/hooks/use-conversations';
import { DEFAULT_FILTERS } from '@/hooks/use-conversations';
import type { InboxView } from '@/types/omnichannel';
import {
  mockPendingActionsService,
  resetMockPendingActions,
  setMockWindowSeconds,
} from '@/services/pending-actions-service.mock';

import { InboxViewRail } from './inbox-view-rail';

const { useSessionMock } = vi.hoisted(() => ({ useSessionMock: vi.fn() }));
vi.mock('next-auth/react', () => ({ useSession: useSessionMock }));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));

const { useInboxViewsMock } = vi.hoisted(() => ({ useInboxViewsMock: vi.fn() }));
vi.mock('@/hooks/use-inbox-views', () => ({ useInboxViews: useInboxViewsMock }));

const { useStatusGraphMock } = vi.hoisted(() => ({ useStatusGraphMock: vi.fn() }));
vi.mock('@/hooks/use-status-engine', () => ({ useStatusGraph: useStatusGraphMock }));

// The real deferred-action hook runs against the mock pending-actions
// service (matches `use-deferred-action.test.ts`'s own convention) so the
// delete flow exercises the real park/poll/commit/cancel state machine.
vi.mock('@/services/pending-actions-service', () => ({
  pendingActionsService: mockPendingActionsService,
}));

// `deferredToast`/`dismissDeferredToast` AND `toast.success`/`toast.error`
// all go through `sonner` directly - mock it once so both are observable.
const { customMock, dismissMock } = vi.hoisted(() => ({
  customMock: vi.fn((_render: unknown, options: { id: string }) => options.id),
  dismissMock: vi.fn(),
}));
vi.mock('sonner', () => ({
  toast: {
    custom: customMock,
    dismiss: dismissMock,
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    message: vi.fn(),
  },
}));

function withSession(userId: string, perms: string[] = []) {
  useSessionMock.mockReturnValue({
    status: 'authenticated',
    data: { user: { id: userId, permissions: perms } },
  });
}

function view(over: Partial<InboxView> = {}): InboxView {
  return {
    id: 'view-1',
    workspaceId: 'wsp-001',
    name: 'My view',
    ownerUserId: 'usr-owner',
    ownerName: 'Owner',
    isShared: false,
    filter: {},
    sortOrder: 0,
    createdAt: '2026-01-01T00:00:00Z',
    ...over,
  };
}

function renderRail(
  views: InboxView[],
  filters: ConversationFilters = DEFAULT_FILTERS,
  setFilters: (patch: Partial<ConversationFilters>) => void = vi.fn(),
) {
  const refresh = vi.fn();
  useInboxViewsMock.mockReturnValue({
    views,
    create: vi.fn(),
    update: vi.fn(),
    refresh,
  });
  useStatusGraphMock.mockReturnValue({ graph: null });
  render(
    <InboxViewRail workspaceId="wsp-001" filters={filters} setFilters={setFilters} variant="sidebar" />,
  );
  return { refresh };
}

/** Open a view's manage menu and click Delete - the delete flow is a
 *  deferred (grace-window) action, never a confirm dialog. `userEvent` (not
 *  bare `fireEvent`) is required: Radix's Menu trigger opens off a real
 *  pointerdown+click sequence that a single synthetic `click` doesn't
 *  reproduce. */
async function openMenuAndDelete(viewId: string) {
  const user = userEvent.setup();
  await act(async () => {
    await user.click(screen.getByTestId(`rail-view-menu-${viewId}`));
  });
  const deleteItem = await screen.findByText('Delete');
  await act(async () => {
    await user.click(deleteItem);
    // Flush the awaited `park()` microtask inside `deleteView()`.
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('InboxViewRail - manage control by real owner', () => {
  it('shows Manage for the caller\'s OWN view (matched by the real session user id)', () => {
    withSession('usr-owner', []);
    renderRail([view({ ownerUserId: 'usr-owner' })]);
    expect(screen.getByTestId('rail-view-menu-view-1')).toBeInTheDocument();
  });

  it('hides Manage for another user\'s view without inbox_views.manage', () => {
    withSession('usr-other', []);
    renderRail([view({ ownerUserId: 'usr-owner' })]);
    expect(screen.queryByTestId('rail-view-menu-view-1')).not.toBeInTheDocument();
  });

  it('shows Manage for another user\'s view WITH inbox_views.manage', () => {
    withSession('usr-other', ['inbox_views.manage']);
    renderRail([view({ ownerUserId: 'usr-owner' })]);
    expect(screen.getByTestId('rail-view-menu-view-1')).toBeInTheDocument();
  });

  it('hides Manage for a SHARED view the caller does not own, without the permission', () => {
    withSession('usr-other', []);
    renderRail([view({ ownerUserId: 'usr-owner', isShared: true })]);
    expect(screen.queryByTestId('rail-view-menu-view-1')).not.toBeInTheDocument();
  });
});

describe('InboxViewRail - delete is a deferred action (review round 2)', () => {
  beforeEach(() => {
    resetMockPendingActions();
    // A tiny real window (not the production 10s) - the hook's 1s poll tick
    // is a fixed real `setInterval`, so these tests wait real wall-clock
    // time rather than fake timers (Radix's Menu open needs a REAL
    // pointerdown+click sequence via `userEvent`, which doesn't mix
    // reliably with `vi.useFakeTimers()`).
    setMockWindowSeconds('destructive', 0.05);
    customMock.mockClear();
    dismissMock.mockClear();
    // `?view=` written by a prior test's `writeUrlKey` call would otherwise
    // leak into this one (jsdom's `window.location` persists across tests
    // in the same file) and trigger `useInboxRailSelection`'s own
    // restore-from-URL effect - unrelated to the delete flow under test.
    window.history.replaceState(null, '', '/');
  });

  it('Delete parks `inbox_views.delete` via the pending-actions service - no confirm dialog (finding 4)', async () => {
    withSession('usr-owner', []);
    renderRail([view({ id: 'view-1', ownerUserId: 'usr-owner' })]);

    await openMenuAndDelete('view-1');

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    const current = await mockPendingActionsService.current('inbox_view', 'view-1');
    expect(current.pending?.actionKey).toBe('inbox_views.delete');
    expect(customMock).toHaveBeenCalledTimes(1);
  });

  it('deleting the currently-selected view falls back to All once it commits (finding 2)', async () => {
    withSession('usr-owner', []);
    const setFilters = vi.fn();
    const selectedFilters: ConversationFilters = { ...DEFAULT_FILTERS, viewId: 'view-1' };
    renderRail([view({ id: 'view-1', ownerUserId: 'usr-owner' })], selectedFilters, setFilters);

    await openMenuAndDelete('view-1');

    // Past the (tiny) window; the 1s poll tick discovers the commit and
    // fires `onCommitted`.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1300));
    });

    expect(setFilters).toHaveBeenCalledWith({ assignee: 'all', lifecycleStageIds: [], viewId: null });
    // The URL falls back to the All rail entry's key too (never left
    // pointing at the deleted view).
    expect(new URLSearchParams(window.location.search).get('view')).toBe('all');
  }, 10_000);

  it('does NOT reset filters when a DIFFERENT view (not the selected one) is deleted', async () => {
    withSession('usr-owner', []);
    const setFilters = vi.fn();
    const selectedFilters: ConversationFilters = { ...DEFAULT_FILTERS, viewId: 'view-2' };
    renderRail(
      [view({ id: 'view-1', ownerUserId: 'usr-owner' }), view({ id: 'view-2', name: 'Other view', ownerUserId: 'usr-owner' })],
      selectedFilters,
      setFilters,
    );

    await openMenuAndDelete('view-1');
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1300));
    });

    expect(setFilters).not.toHaveBeenCalled();
  }, 10_000);

  it('starting a second delete settles the first toast - Undo on the second cancels only the second (finding 3)', async () => {
    withSession('usr-owner', []);
    // This test asserts view-1's park is STILL pending at the end (never
    // touched by view-2's cancel) - a long window keeps it from
    // auto-committing under real-clock system load mid-assertion (unlike
    // the commit-focused tests above, this one deliberately never lets the
    // window lapse).
    setMockWindowSeconds('destructive', 10);
    renderRail([
      view({ id: 'view-1', ownerUserId: 'usr-owner' }),
      view({ id: 'view-2', name: 'Other view', ownerUserId: 'usr-owner' }),
    ]);

    await openMenuAndDelete('view-1');
    expect(customMock).toHaveBeenCalledTimes(1);
    const [, firstOptions] = customMock.mock.calls[0] as [unknown, { id: string }];
    expect(dismissMock).not.toHaveBeenCalled();

    await openMenuAndDelete('view-2');

    // Starting the second delete settled (dismissed) the first toast...
    expect(dismissMock).toHaveBeenCalledWith(firstOptions.id);
    // ...and rendered a NEW toast for the second view.
    expect(customMock).toHaveBeenCalledTimes(2);
    const [secondRender, secondOptions] = customMock.mock.calls[1] as [
      () => { props: { onCancel: () => void } },
      { id: string },
    ];
    expect(secondOptions.id).not.toBe(firstOptions.id);

    // Undo on the SECOND toast cancels ONLY view-2's parked action - view-1's
    // is untouched (still parked, resolves on its own countdown).
    const secondElement = secondRender();
    await act(async () => {
      secondElement.props.onCancel();
      await Promise.resolve();
      await Promise.resolve();
    });

    const view2State = await mockPendingActionsService.current('inbox_view', 'view-2');
    expect(view2State.lastOutcome?.status).toBe('cancelled');
    const view1State = await mockPendingActionsService.current('inbox_view', 'view-1');
    expect(view1State.pending?.actionKey).toBe('inbox_views.delete');
  });
});
