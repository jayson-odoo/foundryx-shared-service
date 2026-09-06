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
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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

// Plan 28 (roadmap A8, D-A8-4) - the rail's folded-in Teams section. Default
// to "no teams" so the pre-existing (plan 27) tests below render exactly as
// they did before the fold-in; the dedicated Teams describe block overrides
// these per test.
const { useMyTeamsMock, useTeamsMock } = vi.hoisted(() => ({ useMyTeamsMock: vi.fn(), useTeamsMock: vi.fn() }));
vi.mock('@/hooks/use-my-teams', () => ({ useMyTeams: useMyTeamsMock }));
vi.mock('@/hooks/use-teams', () => ({ useTeams: useTeamsMock }));
useMyTeamsMock.mockReturnValue({ teams: [], isLoading: false, error: null, reload: vi.fn() });
useTeamsMock.mockReturnValue({ teams: [], isLoading: false, error: null, reload: vi.fn() });

// The real deferred-action hook runs against the mock pending-actions
// service (matches `use-deferred-action.test.ts`'s own convention) so the
// delete flow exercises the real park/poll/commit/cancel state machine.
vi.mock('@/services/pending-actions-service', () => ({
  pendingActionsService: mockPendingActionsService,
}));

// `deferredToast`/`dismissDeferredToast` AND `toast.success`/`toast.error`
// all go through `sonner` directly - mock it once so both are observable.
const { customMock, dismissMock, errorMock } = vi.hoisted(() => ({
  customMock: vi.fn((_render: unknown, options: { id: string }) => options.id),
  dismissMock: vi.fn(),
  errorMock: vi.fn(),
}));
vi.mock('sonner', () => ({
  toast: {
    custom: customMock,
    dismiss: dismissMock,
    success: vi.fn(),
    error: errorMock,
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
    errorMock.mockClear();
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

    expect(setFilters).toHaveBeenCalledWith({
      assignee: 'all', lifecycleStageIds: [], tagIds: [], channelIds: [], viewId: null, teamId: null,
    });
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

  it('refuses a second delete while the first is still counting down (round-3 codex triage F3, supersedes review round 2 finding 3)', async () => {
    withSession('usr-owner', []);
    // F3: ONE `useDeferredAction` instance serves every row - `start()`
    // OVERWRITES `parkedRef` wholesale, so settling-then-overwriting (the
    // OLD behavior) would silently stop polling/refreshing/toasting for
    // view-1 the instant view-2's delete started (view-1's server-side
    // action still resolves, but this component would never learn it did).
    // The safe fix refuses the second start outright - the first toast
    // stays untouched and view-1's park is unaffected.
    setMockWindowSeconds('destructive', 10);
    renderRail([
      view({ id: 'view-1', ownerUserId: 'usr-owner' }),
      view({ id: 'view-2', name: 'Other view', ownerUserId: 'usr-owner' }),
    ]);

    await openMenuAndDelete('view-1');
    expect(customMock).toHaveBeenCalledTimes(1);

    await openMenuAndDelete('view-2');

    // The second delete never started - no new toast, the first is
    // untouched, and the user is told why.
    expect(customMock).toHaveBeenCalledTimes(1);
    expect(dismissMock).not.toHaveBeenCalled();
    expect(errorMock.mock.calls[0][0]).toContain('Finish deleting');

    const view1State = await mockPendingActionsService.current('inbox_view', 'view-1');
    expect(view1State.pending?.actionKey).toBe('inbox_views.delete');
    const view2State = await mockPendingActionsService.current('inbox_view', 'view-2');
    expect(view2State.pending).toBeNull();

    // Undo on the (only) first toast still cancels view-1 cleanly.
    const [firstRender] = customMock.mock.calls[0] as [() => { props: { onCancel: () => void } }, { id: string }];
    const firstElement = firstRender();
    await act(async () => {
      firstElement.props.onCancel();
      await Promise.resolve();
      await Promise.resolve();
    });
    const cancelledView1 = await mockPendingActionsService.current('inbox_view', 'view-1');
    expect(cancelledView1.lastOutcome?.status).toBe('cancelled');
  });
});

// Plan 28 (roadmap A8, D-A8-4) - Teams folded into this rail as a third
// section (mirrors the retired standalone `TeamRail`'s own test coverage:
// `use-conversations.test.ts` still covers the query-param side of
// "selection -> URL").
describe('InboxViewRail - Teams (plan 28, D-A8-4)', () => {
  afterEach(() => {
    useMyTeamsMock.mockReturnValue({ teams: [], isLoading: false, error: null, reload: vi.fn() });
    useTeamsMock.mockReturnValue({ teams: [], isLoading: false, error: null, reload: vi.fn() });
    window.history.replaceState(null, '', '/');
  });

  it('clears a stale ?view= param when a team entry is selected', async () => {
    window.history.replaceState(null, '', '/?view=me');
    withSession('usr-1', []);
    useMyTeamsMock.mockReturnValue({
      teams: [{ id: 'team-1', name: 'Sales' }], isLoading: false, error: null, reload: vi.fn(),
    });
    useTeamsMock.mockReturnValue({
      teams: [{ id: 'team-1', name: 'Sales' }], isLoading: false, error: null, reload: vi.fn(),
    });
    renderRail([]);

    const user = userEvent.setup();
    await user.click(screen.getByTestId('rail-team:team-1'));
    expect(new URLSearchParams(window.location.search).get('view')).toBeNull();
  });

  it('renders My teams with a nested Unassigned entry and selects on click', async () => {
    withSession('usr-1', []);
    useMyTeamsMock.mockReturnValue({
      teams: [{ id: 'team-1', name: 'Sales' }], isLoading: false, error: null, reload: vi.fn(),
    });
    useTeamsMock.mockReturnValue({
      teams: [{ id: 'team-1', name: 'Sales' }], isLoading: false, error: null, reload: vi.fn(),
    });
    const setFilters = vi.fn();
    renderRail([], DEFAULT_FILTERS, setFilters);

    expect(screen.getByTestId('rail-team:team-1')).toHaveTextContent('Sales');
    // Not privileged (no conversations.assign) - no "All teams" group.
    expect(screen.queryByText('All teams')).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByTestId('rail-team:team-1'));
    expect(setFilters).toHaveBeenLastCalledWith(
      expect.objectContaining({ teamId: 'team-1', assignee: 'all', viewId: null }),
    );

    await user.click(screen.getByTestId('rail-team:team-1:unassigned'));
    expect(setFilters).toHaveBeenLastCalledWith(
      expect.objectContaining({ teamId: 'team-1', assignee: 'unassigned' }),
    );
  });

  it('shows an All teams group for conversations.assign holders (a team not the caller\'s own)', () => {
    withSession('usr-1', ['conversations.assign']);
    useMyTeamsMock.mockReturnValue({
      teams: [{ id: 'team-1', name: 'Sales' }], isLoading: false, error: null, reload: vi.fn(),
    });
    useTeamsMock.mockReturnValue({
      teams: [{ id: 'team-1', name: 'Sales' }, { id: 'team-2', name: 'Support' }],
      isLoading: false, error: null, reload: vi.fn(),
    });
    renderRail([]);
    expect(screen.getByText('All teams')).toBeInTheDocument();
    expect(screen.getByTestId('rail-team:team-2')).toHaveTextContent('Support');
  });

  it('hides the "All teams" group without conversations.assign, even when other teams exist', () => {
    withSession('usr-1', []);
    useMyTeamsMock.mockReturnValue({
      teams: [{ id: 'team-1', name: 'Sales' }], isLoading: false, error: null, reload: vi.fn(),
    });
    useTeamsMock.mockReturnValue({
      teams: [{ id: 'team-1', name: 'Sales' }, { id: 'team-2', name: 'Support' }],
      isLoading: false, error: null, reload: vi.fn(),
    });
    renderRail([]);
    expect(screen.queryByText('All teams')).not.toBeInTheDocument();
    expect(screen.queryByText('Support')).not.toBeInTheDocument();
  });

  it('highlights the currently-selected team entry (via filters.teamId, not local state)', () => {
    withSession('usr-1', []);
    useMyTeamsMock.mockReturnValue({
      teams: [{ id: 'team-1', name: 'Sales' }], isLoading: false, error: null, reload: vi.fn(),
    });
    useTeamsMock.mockReturnValue({
      teams: [{ id: 'team-1', name: 'Sales' }], isLoading: false, error: null, reload: vi.fn(),
    });
    renderRail([], { ...DEFAULT_FILTERS, teamId: 'team-1', assignee: 'unassigned' });
    expect(screen.getByTestId('rail-team:team-1:unassigned')).toHaveClass('bg-accent');
  });
});
