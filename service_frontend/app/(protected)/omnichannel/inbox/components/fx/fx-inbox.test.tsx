/**
 * The inbox with the Foundryx UIUX switch ON (slice W1-INBOX): the list
 * requests match the legacy look for the same choices, the "n new" pill
 * instead of re-sorting under the pointer, the Unreplied switch, relative
 * times on a fixed clock, the phone tabs, the lost-connection banner after
 * 5 s, the rail without counts, and the empty / error states.
 */
import type { ReactNode } from 'react';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConversationThread, ThreadListQuery } from '@/types/omnichannel';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import {
  DEFAULT_FILTERS,
  type ConversationFilters,
} from '@/hooks/use-conversations';
import { FxProvider } from '@/providers/fx-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { resetSystemBannersForTests } from '@/components/fx/banners/banner-store';
import { FxSystemBannerHost } from '@/components/fx/banners/system-banner';
import { FX_CONNECTION_BANNER_TEXT } from '@/components/fx/banners/use-connection-banner';
import {
  INBOX_GRAPH,
  INBOX_TEAMS,
  INBOX_THREADS,
  INBOX_VIEWS,
  inboxThread,
} from '../../__parity__/inbox-fixtures';
import InboxPage from '../../page';
import { fxChatTabLabel, fxClearedFilters } from './fx-inbox-page';
import { FxThreadList } from './fx-thread-list';
import { countWaiting, heldRows, holdOrder } from './held-threads';

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    status: 'authenticated',
    data: {
      user: {
        id: 'usr-demo',
        name: 'Demo User',
        timezone: 'Asia/Kuala_Lumpur',
        permissions: ['conversations.read', 'inbox_views.manage', 'teams.read'],
      },
    },
  }),
  getSession: vi.fn(async () => null),
}));
vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
  usePathname: () => '/omnichannel/inbox',
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn(async () => ({})) },
}));
vi.mock('@/components/common/container', () => ({
  Container: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));
vi.mock('@/services/workspace-service', () => ({
  workspaceService: {
    list: vi.fn(async () => ({ data: [{ id: 'wsp-001', isDefault: true }] })),
  },
}));
const service = vi.hoisted(() => ({
  listThreads: vi.fn(),
  subscribe: vi.fn(),
  connection: null as null | ((connected: boolean) => void),
  events: null as null | ((event: unknown) => void),
}));
vi.mock('@/services/conversation-service', () => ({
  conversationService: service,
}));
vi.mock('@/hooks/use-inbox-views', () => ({
  useInboxViews: () => ({
    views: INBOX_VIEWS,
    create: vi.fn(),
    update: vi.fn(),
    refresh: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-status-engine', () => ({
  useStatusGraph: () => ({ graph: INBOX_GRAPH }),
}));
vi.mock('@/hooks/use-my-teams', () => ({
  useMyTeams: () => ({ teams: INBOX_TEAMS }),
}));
vi.mock('@/hooks/use-teams', () => ({
  useTeams: () => ({ teams: INBOX_TEAMS }),
}));
const wide = vi.hoisted(() => ({ value: true }));
vi.mock('@/hooks/use-media-query', () => ({ useMediaQuery: () => wide.value }));
const paneProps = vi.hoisted(() => ({
  last: null as null | Record<string, unknown>,
}));
vi.mock('@/components/platform/conversation-drawer', async () => {
  const actual = await vi.importActual<
    typeof import('@/components/platform/conversation-drawer')
  >('@/components/platform/conversation-drawer');
  return {
    ...actual,
    ConversationDrawer: (props: {
      contactId: string | null;
      fxPageHeader?: boolean;
    }) => {
      paneProps.last = props;
      return (
        <div data-testid="conversation-pane-stub">
          {props.contactId ?? 'none'}
        </div>
      );
    },
  };
});

function Look({ on, children }: { on: boolean; children: ReactNode }) {
  return (
    <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}

function renderPage(on: boolean) {
  return render(
    <Look on={on}>
      <FxSystemBannerHost />
      <InboxPage />
    </Look>,
  );
}

beforeEach(() => {
  window.history.replaceState(null, '', '/omnichannel/inbox');
  service.listThreads.mockReset();
  service.listThreads.mockResolvedValue(INBOX_THREADS);
  service.subscribe.mockReset();
  service.subscribe.mockImplementation(
    (
      _ws: string,
      handler: (event: unknown) => void,
      onConnection?: (connected: boolean) => void,
    ) => {
      service.events = handler;
      service.connection = onConnection ?? null;
      return () => undefined;
    },
  );
  wide.value = true;
  paneProps.last = null;
  resetPageActionsForTests();
  resetSystemBannersForTests();
});

afterEach(() => {
  vi.useRealTimers();
});

async function pick(
  user: ReturnType<typeof userEvent.setup>,
  box: string,
  option: string,
) {
  await user.click(screen.getByRole('combobox', { name: box }));
  await user.click(await screen.findByRole('option', { name: option }));
}

/** The same choices, made by mouse, in one look; returns every list request. */
async function requestsFor(on: boolean): Promise<ThreadListQuery[]> {
  // Each look starts from the same address (the rail writes `?view=`).
  window.history.replaceState(null, '', '/omnichannel/inbox');
  const user = userEvent.setup();
  const view = renderPage(on);
  await screen.findByTestId('thread-row-cnt-003');
  await pick(user, 'Show', 'Open');
  await pick(user, 'Sort', 'Oldest');
  await pick(user, 'Priority filter', 'Urgent');
  await user.click(screen.getByTestId('inbox-unreplied'));
  await user.click(screen.getByTestId('rail-me'));
  await user.click(screen.getByTestId('rail-lifecycle:stg-2'));
  await user.click(screen.getByTestId('rail-team:team-1:unassigned'));
  await user.type(screen.getByTestId('thread-search'), 'ai');
  await user.click(screen.getByTestId('rail-view-view-1'));
  await user.click(screen.getByTestId('rail-all'));
  await waitFor(() =>
    expect(service.listThreads.mock.calls.length).toBeGreaterThan(9),
  );
  const calls = service.listThreads.mock.calls.map(
    ([q]) => q as ThreadListQuery,
  );
  view.unmount();
  service.listThreads.mockClear();
  return calls;
}

describe('list requests are the same in both looks', () => {
  it('sends identical query parameters for the same filter choices', async () => {
    const off = await requestsFor(false);
    const on = await requestsFor(true);
    expect(on).toEqual(off);
    expect(off).toHaveLength(12);
    // Every choice reached the request.
    expect(off.some((q) => q.status === 'OPEN' && q.statusExplicit)).toBe(true);
    expect(off.some((q) => q.sort === 'oldest')).toBe(true);
    expect(off.some((q) => q.priority === 'URGENT')).toBe(true);
    expect(off.some((q) => q.unreplied)).toBe(true);
    expect(off.some((q) => q.assignee === 'me')).toBe(true);
    expect(off.some((q) => q.lifecycleStageIds?.includes('stg-2'))).toBe(true);
    expect(
      off.some((q) => q.teamId === 'team-1' && q.assignee === 'unassigned'),
    ).toBe(true);
    expect(off.some((q) => q.search === 'ai')).toBe(true);
    expect(off.some((q) => q.viewId === 'view-1')).toBe(true);
  }, 30_000);
});

describe('slim page header and the conversation pane', () => {
  it('shows the slim header and hands the red action to it (fxPageHeader)', async () => {
    window.history.replaceState(null, '', '/omnichannel/inbox?thread=cnt-001');
    renderPage(true);
    await screen.findByTestId('thread-row-cnt-001');
    expect(
      screen.getByRole('heading', { level: 1, name: 'Inbox' }),
    ).toBeInTheDocument();
    expect(document.querySelector('[data-fx-header]')).not.toBeNull();
    expect(paneProps.last).toMatchObject({
      contactId: 'cnt-001',
      fxPageHeader: true,
    });
  });

  it('switch off: no page header and the pane draws its own action', async () => {
    renderPage(false);
    await screen.findByTestId('thread-row-cnt-001');
    expect(screen.queryByRole('heading', { level: 1 })).toBeNull();
    expect(paneProps.last?.fxPageHeader).toBeUndefined();
  });

  it('keeps the three panes at desktop width with no hover-widen', async () => {
    renderPage(true);
    const shell = await screen.findByTestId('inbox-shell');
    await screen.findByTestId('thread-row-cnt-001');
    expect(shell.className).toContain('grid-cols-[200px_320px_minmax(0,1fr)]');
    fireEvent.pointerOver(screen.getByTestId('thread-list-scroller'), {
      pointerType: 'mouse',
    });
    expect(shell.className).toContain('grid-cols-[200px_320px_minmax(0,1fr)]');
    expect(screen.getByTestId('inbox-view-rail')).toBeInTheDocument();
    expect(screen.getByTestId('conversation-pane-stub')).toBeInTheDocument();
  });
});

describe('the rail', () => {
  it('shows no counts beside its entries (the API returns none)', async () => {
    renderPage(true);
    await screen.findByTestId('thread-row-cnt-001');
    for (const id of [
      'rail-all',
      'rail-me',
      'rail-unassigned',
      'rail-lifecycle:stg-1',
      'rail-view-view-1',
    ]) {
      expect(screen.getByTestId(id).textContent).not.toMatch(/\d/);
    }
  });

  it('marks the chosen entry for screen readers', async () => {
    const user = userEvent.setup();
    renderPage(true);
    await screen.findByTestId('thread-row-cnt-001');
    expect(screen.getByTestId('rail-all')).toHaveAttribute(
      'aria-current',
      'true',
    );
    await user.click(screen.getByTestId('rail-me'));
    expect(screen.getByTestId('rail-me')).toHaveAttribute(
      'aria-current',
      'true',
    );
    expect(screen.getByTestId('rail-all')).not.toHaveAttribute('aria-current');
  });
});

describe('Show / Sort / Priority and Unreplied', () => {
  it('draws the playbook dropdowns and the playbook switch', async () => {
    const user = userEvent.setup();
    renderPage(true);
    await screen.findByTestId('thread-row-cnt-001');
    const bar = screen.getByTestId('inbox-filter-bar');
    expect(within(bar).getAllByRole('combobox')).toHaveLength(3);
    const sw = screen.getByRole('switch', { name: 'Unreplied only' });
    expect(sw).toHaveAttribute('data-fx-switch');
    expect(sw).toHaveAttribute('aria-checked', 'false');
    await user.click(sw);
    expect(sw).toHaveAttribute('aria-checked', 'true');
    await waitFor(() =>
      expect(service.listThreads).toHaveBeenLastCalledWith(
        expect.objectContaining({ unreplied: true }),
      ),
    );
  });
});

describe('thread list times', () => {
  it('reads relative times against a fixed clock, with the 12-hour moment as tooltip', () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-06-05T08:00:00Z'));
    render(
      <Look on>
        <FxThreadList
          threads={INBOX_THREADS}
          isLoading={false}
          error={null}
          filters={DEFAULT_FILTERS}
          setFilters={vi.fn()}
          selectedId="cnt-002"
          onSelect={vi.fn()}
        />
      </Look>,
    );
    const time = (id: string) =>
      screen
        .getByTestId(`thread-row-${id}`)
        .querySelector('time') as HTMLElement;
    expect(time('cnt-001')).toHaveTextContent('5 min');
    expect(time('cnt-001')).toHaveAttribute('title', '5 Jun 2026, 3:55 pm');
    expect(time('cnt-002')).toHaveTextContent('3 h');
    expect(time('cnt-003')).toHaveTextContent('2 Jun');
    expect(screen.getByTestId('thread-row-cnt-002')).toHaveAttribute(
      'aria-current',
      'true',
    );
  });
});

describe('rows never move under the pointer', () => {
  const a = inboxThread({
    id: 'a',
    name: 'Alpha One',
    lastMessageAt: '2026-06-05T07:00:00Z',
    lastMessagePreview: 'first',
  });
  const b = inboxThread({
    id: 'b',
    name: 'Bravo Two',
    lastMessageAt: '2026-06-05T06:00:00Z',
  });
  const c = inboxThread({
    id: 'c',
    name: 'Charlie Three',
    lastMessageAt: '2026-06-05T07:59:00Z',
  });

  it('pure helpers: frozen order, live values, waiting count', () => {
    const held = holdOrder([a, b]);
    const aNewer = {
      ...a,
      lastMessageAt: '2026-06-05T07:58:00Z',
      lastMessagePreview: 'second',
    };
    const live = [c, aNewer, b];
    expect(heldRows(held, live).map((t) => t.id)).toEqual(['a', 'b']);
    expect(heldRows(held, live)[0].lastMessagePreview).toBe('second');
    expect(countWaiting(held, live)).toBe(2);
    expect(heldRows(held, [b]).map((t) => t.id)).toEqual(['b']);
  });

  function List({
    threads,
    filters = DEFAULT_FILTERS,
  }: {
    threads: ConversationThread[];
    filters?: ConversationFilters;
  }) {
    return (
      <Look on>
        <FxThreadList
          threads={threads}
          isLoading={false}
          error={null}
          filters={filters}
          setFilters={vi.fn()}
          selectedId={null}
          onSelect={vi.fn()}
        />
      </Look>
    );
  }
  const order = () =>
    screen
      .getAllByRole('button')
      .filter((el) => el.dataset.testid?.startsWith('thread-row-'))
      .map((el) => el.dataset.testid);

  it('shows a "n new" pill instead of re-sorting, and applies the order on click', async () => {
    const user = userEvent.setup();
    const view = render(<List threads={[a, b]} />);
    fireEvent.pointerOver(screen.getByTestId('thread-list-scroller'), {
      pointerType: 'mouse',
    });
    const aNewer = {
      ...a,
      lastMessageAt: '2026-06-05T07:58:00Z',
      lastMessagePreview: 'second',
    };
    view.rerender(<List threads={[c, aNewer, b]} />);
    expect(order()).toEqual(['thread-row-a', 'thread-row-b']);
    expect(screen.getByTestId('thread-row-a')).toHaveTextContent('second');
    const pill = screen.getByTestId('thread-list-new-pill');
    expect(pill).toHaveTextContent('2 new');
    await user.click(pill);
    expect(order()).toEqual(['thread-row-c', 'thread-row-a', 'thread-row-b']);
    expect(screen.queryByTestId('thread-list-new-pill')).toBeNull();
  });

  it('applies the live order once the pointer leaves a list scrolled to the top', () => {
    const view = render(<List threads={[a, b]} />);
    const scroller = screen.getByTestId('thread-list-scroller');
    fireEvent.pointerOver(scroller, { pointerType: 'mouse' });
    view.rerender(<List threads={[c, a, b]} />);
    expect(order()).toEqual(['thread-row-a', 'thread-row-b']);
    fireEvent.pointerOut(scroller, { pointerType: 'mouse' });
    expect(order()).toEqual(['thread-row-c', 'thread-row-a', 'thread-row-b']);
  });

  it('re-sorts at once when the pointer is elsewhere and the list is at the top', () => {
    const view = render(<List threads={[a, b]} />);
    view.rerender(<List threads={[c, a, b]} />);
    expect(order()).toEqual(['thread-row-c', 'thread-row-a', 'thread-row-b']);
    expect(screen.queryByTestId('thread-list-new-pill')).toBeNull();
  });

  it('a new filter brings a new list, never "new" rows', () => {
    // A filter change keeps the old list on screen until its fetch answers.
    const first = [a, b];
    const view = render(<List threads={first} />);
    fireEvent.pointerOver(screen.getByTestId('thread-list-scroller'), {
      pointerType: 'mouse',
    });
    const filtered = { ...DEFAULT_FILTERS, priority: 'URGENT' as const };
    view.rerender(<List threads={first} filters={filtered} />);
    view.rerender(<List threads={[c, b]} filters={filtered} />);
    expect(order()).toEqual(['thread-row-c', 'thread-row-b']);
    expect(screen.queryByTestId('thread-list-new-pill')).toBeNull();
  });
});

describe('empty and error states', () => {
  it('nothing matches: says so and offers Clear filters', async () => {
    const onClear = vi.fn();
    const user = userEvent.setup();
    render(
      <Look on>
        <FxThreadList
          threads={[]}
          isLoading={false}
          error={null}
          filters={{ ...DEFAULT_FILTERS, unreplied: true }}
          setFilters={vi.fn()}
          selectedId={null}
          onSelect={vi.fn()}
          onClearFilters={onClear}
        />
      </Look>,
    );
    expect(
      screen.getByText('No conversations match these filters.'),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(onClear).toHaveBeenCalled();
  });

  it("nothing here yet, and couldn't load with Try again", async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    const view = render(
      <Look on>
        <FxThreadList
          threads={[]}
          isLoading={false}
          error={null}
          filters={DEFAULT_FILTERS}
          setFilters={vi.fn()}
          selectedId={null}
          onSelect={vi.fn()}
        />
      </Look>,
    );
    expect(
      screen.getByText('Conversations show here when contacts message you.'),
    ).toBeInTheDocument();
    view.unmount();
    render(
      <Look on>
        <FxThreadList
          threads={[]}
          isLoading={false}
          error="boom 500"
          filters={DEFAULT_FILTERS}
          setFilters={vi.fn()}
          selectedId={null}
          onSelect={vi.fn()}
          onRetry={onRetry}
        />
      </Look>,
    );
    expect(
      screen.getByText("Couldn't load the conversations."),
    ).toBeInTheDocument();
    expect(screen.queryByText('boom 500')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(onRetry).toHaveBeenCalled();
  });

  it('Clear filters goes back to All and the bar defaults, keeping the sort', () => {
    expect(fxClearedFilters()).toEqual({
      assignee: 'all',
      lifecycleStageIds: [],
      tagIds: [],
      channelIds: [],
      viewId: null,
      teamId: null,
      status: 'ALL',
      statusExplicit: false,
      priority: 'ALL',
      unreplied: false,
      search: '',
    });
  });
});

describe('phones: browser-style tabs', () => {
  it('shows Conversations and the open chat as tabs, opening a conversation switches tab', async () => {
    wide.value = false;
    const user = userEvent.setup();
    renderPage(true);
    await screen.findByTestId('thread-row-cnt-002');
    const tabs = screen.getByRole('tablist', { name: 'Inbox panels' });
    expect(within(tabs).getAllByRole('tab')).toHaveLength(2);
    expect(screen.getByTestId('inbox-tab-list')).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByTestId('inbox-tab-list')).toHaveTextContent(
      'Conversations3',
    );
    expect(screen.getByTestId('inbox-tab-chat')).toHaveTextContent('Chat');

    await user.click(screen.getByTestId('thread-row-cnt-002'));
    expect(screen.getByTestId('inbox-tab-chat')).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByTestId('inbox-tab-chat')).toHaveTextContent('Wei Jie');
    expect(document.getElementById('inbox-panel-list')).toHaveAttribute(
      'hidden',
    );
    expect(screen.getByTestId('conversation-pane-stub')).toHaveTextContent(
      'cnt-002',
    );

    // Back to the list keeps the chat open in its tab (each tab keeps its state).
    await user.click(screen.getByTestId('inbox-tab-list'));
    expect(document.getElementById('inbox-panel-chat')).toHaveAttribute(
      'hidden',
    );
    expect(screen.getByTestId('conversation-pane-stub')).toHaveTextContent(
      'cnt-002',
    );
    expect(new URLSearchParams(window.location.search).get('thread')).toBe(
      'cnt-002',
    );
    // No one-pane back button under the new look.
    expect(screen.queryByTestId('inbox-back')).toBeNull();
  });

  it('names the chat tab by the first name', () => {
    expect(fxChatTabLabel(undefined)).toBe('Chat');
    expect(
      fxChatTabLabel(inboxThread({ firstName: null, name: 'Kumar Ravi' })),
    ).toBe('Kumar');
    expect(fxChatTabLabel(inboxThread())).toBe('Aisyah');
  });
});

describe('lost connection', () => {
  it('shows the banner only after 5 s without the feed, then refetches once back', async () => {
    renderPage(true);
    await screen.findByTestId('thread-row-cnt-001');
    await waitFor(() => expect(service.connection).not.toBeNull());
    vi.useFakeTimers();
    const before = service.listThreads.mock.calls.length;

    act(() => service.connection?.(false));
    act(() => vi.advanceTimersByTime(4900));
    expect(screen.queryByText(FX_CONNECTION_BANNER_TEXT)).toBeNull();
    act(() => vi.advanceTimersByTime(200));
    expect(screen.getByText(FX_CONNECTION_BANNER_TEXT)).toBeInTheDocument();

    act(() => service.connection?.(true));
    act(() => vi.advanceTimersByTime(1000)); // the bar slides away
    expect(screen.queryByText(FX_CONNECTION_BANNER_TEXT)).toBeNull();
    expect(service.listThreads.mock.calls.length).toBe(before + 1);
  });

  it('a short drop that fixes itself shows nothing and fetches nothing', async () => {
    renderPage(true);
    await screen.findByTestId('thread-row-cnt-001');
    await waitFor(() => expect(service.connection).not.toBeNull());
    vi.useFakeTimers();
    const before = service.listThreads.mock.calls.length;
    act(() => service.connection?.(false));
    act(() => vi.advanceTimersByTime(3000));
    act(() => service.connection?.(true));
    act(() => vi.advanceTimersByTime(5000));
    expect(screen.queryByText(FX_CONNECTION_BANNER_TEXT)).toBeNull();
    expect(service.listThreads.mock.calls.length).toBe(before);
  });

  it('switch off: never a banner', async () => {
    renderPage(false);
    await screen.findByTestId('thread-row-cnt-001');
    await waitFor(() => expect(service.connection).not.toBeNull());
    vi.useFakeTimers();
    act(() => service.connection?.(false));
    act(() => vi.advanceTimersByTime(6000));
    expect(screen.queryByText(FX_CONNECTION_BANNER_TEXT)).toBeNull();
  });
});
