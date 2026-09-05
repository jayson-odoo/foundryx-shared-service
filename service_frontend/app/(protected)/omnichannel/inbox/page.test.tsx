/** AC-IVE-24/48 - below `lg` the inbox is ONE pane at a time (the thread
 *  list, or the open conversation with a back control) - no rail + list +
 *  drawer all rendered together like the >=lg layout. */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import InboxPage from './page';

vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Container reads layout tokens via useSettings() (SettingsProvider) - not
// under test here, so render its children directly (same pattern as
// `app/(protected)/ideation/board/page.test.tsx`).
vi.mock('@/components/common/container', () => ({
  Container: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock('@/services/workspace-service', () => ({
  workspaceService: {
    list: vi.fn().mockResolvedValue({ data: [{ id: 'wsp-001', isDefault: true }] }),
  },
}));

const { useConversationsMock } = vi.hoisted(() => ({ useConversationsMock: vi.fn() }));
vi.mock('@/hooks/use-conversations', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/use-conversations')>('@/hooks/use-conversations');
  return { ...actual, useConversations: useConversationsMock };
});

const { useMediaQueryMock } = vi.hoisted(() => ({ useMediaQueryMock: vi.fn() }));
vi.mock('@/hooks/use-media-query', () => ({ useMediaQuery: useMediaQueryMock }));

vi.mock('./components/inbox-view-rail', () => ({
  InboxViewRail: ({ variant }: { variant?: string }) => <div data-testid={`rail-${variant}`} />,
}));
vi.mock('./components/inbox-filter-bar', () => ({
  InboxFilterBar: () => <div data-testid="filter-bar" />,
}));
vi.mock('./components/thread-list', () => ({
  ThreadList: ({ onSelect }: { onSelect: (id: string) => void }) => (
    <button type="button" onClick={() => onSelect('cnt-001')} data-testid="pick-thread">
      Open thread
    </button>
  ),
}));
vi.mock('@/components/platform/conversation-drawer', () => ({
  ConversationDrawer: ({ contactId }: { contactId: string | null }) => (
    <div data-testid="conversation-drawer">{contactId}</div>
  ),
}));

function setup() {
  useConversationsMock.mockReturnValue({
    threads: [],
    isLoading: false,
    error: null,
    filters: {
      assignee: 'all', status: 'ALL', priority: 'ALL', search: '',
      lifecycleStageIds: [], tagIds: [], channelIds: [], unreplied: false, sort: 'newest', viewId: null,
    },
    setFilters: vi.fn(),
  });
}

describe('InboxPage - responsive single-pane switch (D-A3-15)', () => {
  // `openThread` reads/writes `?thread=` on the REAL jsdom `window.history`,
  // which persists across tests in this file (RTL only unmounts the React
  // tree) - reset it or a later test inherits the previous test's selection.
  beforeEach(() => {
    window.history.replaceState(null, '', '/');
  });

  it('at >=lg renders the rail, the list AND the drawer side by side', async () => {
    setup();
    useMediaQueryMock.mockReturnValue(true); // isDesktop
    render(<InboxPage />);

    expect(await screen.findByTestId('rail-sidebar')).toBeInTheDocument();
    expect(screen.getByTestId('pick-thread')).toBeInTheDocument();
    expect(screen.getByTestId('conversation-drawer')).toBeInTheDocument();
    // No mobile-only View select or back control at desktop width.
    expect(screen.queryByTestId('rail-select')).not.toBeInTheDocument();
    expect(screen.queryByTestId('inbox-back')).not.toBeInTheDocument();
  });

  it('below lg shows ONLY the list (View select above it) until a thread is opened', async () => {
    setup();
    useMediaQueryMock.mockReturnValue(false); // !isDesktop
    render(<InboxPage />);

    expect(await screen.findByTestId('rail-select')).toBeInTheDocument();
    expect(screen.getByTestId('pick-thread')).toBeInTheDocument();
    expect(screen.queryByTestId('rail-sidebar')).not.toBeInTheDocument();
    expect(screen.queryByTestId('conversation-drawer')).not.toBeInTheDocument();
  });

  it('below lg, opening a thread swaps to ONE pane (conversation + back control), list gone', async () => {
    setup();
    useMediaQueryMock.mockReturnValue(false);
    const user = userEvent.setup();
    render(<InboxPage />);

    await user.click(await screen.findByTestId('pick-thread'));

    expect(screen.getByTestId('conversation-drawer')).toHaveTextContent('cnt-001');
    expect(screen.getByTestId('inbox-back')).toBeInTheDocument();
    expect(screen.queryByTestId('pick-thread')).not.toBeInTheDocument();
    expect(screen.queryByTestId('rail-select')).not.toBeInTheDocument();
  });

  it('below lg, the back control returns to the list pane', async () => {
    setup();
    useMediaQueryMock.mockReturnValue(false);
    const user = userEvent.setup();
    render(<InboxPage />);

    await user.click(await screen.findByTestId('pick-thread'));
    await user.click(screen.getByTestId('inbox-back'));

    expect(screen.getByTestId('pick-thread')).toBeInTheDocument();
    expect(screen.queryByTestId('conversation-drawer')).not.toBeInTheDocument();
  });
});
