/**
 * Switch-off parity for the inbox page (Foundryx UIUX slice W1-INBOX, build
 * plan 1.3 and 4): the page at desktop and phone widths, the view rail (both
 * renderings), the Show / Sort / Unreplied bar, the thread list (rows, empty,
 * error, loading) and the save-view dialog, rendered with the switch OFF.
 * Recorded on the code as it was before the slice; a change that needs one of
 * these snapshots updated is wrong by definition (fix the code, never the
 * snapshot). Generated ids are renamed in order of appearance and clock times
 * are masked, so the snapshots hold markup only. The conversation pane has its
 * own parity suite and is stubbed here.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { DEFAULT_FILTERS } from '@/hooks/use-conversations';

import {
  INBOX_GRAPH,
  INBOX_NOW,
  INBOX_TEAMS,
  INBOX_THREADS,
  INBOX_VIEWS,
} from './inbox-fixtures';

vi.hoisted(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-06-05T08:00:00Z'));
});

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
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => '/omnichannel/inbox',
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock('@/components/common/container', () => ({
  Container: ({ children, className }: { children: React.ReactNode; className?: string }) => (
    <div data-container={className}>{children}</div>
  ),
}));
vi.mock('@/services/workspace-service', () => ({
  workspaceService: {
    list: vi.fn(async () => ({ data: [{ id: 'wsp-001', isDefault: true }] })),
  },
}));
const listThreads = vi.hoisted(() => vi.fn());
vi.mock('@/services/conversation-service', () => ({
  conversationService: { listThreads, subscribe: vi.fn(() => () => undefined) },
}));
vi.mock('@/hooks/use-conversation-socket', () => ({ useConversationSocket: () => undefined }));
vi.mock('@/hooks/use-inbox-views', () => ({
  useInboxViews: () => ({ views: INBOX_VIEWS, create: vi.fn(), update: vi.fn(), refresh: vi.fn() }),
}));
vi.mock('@/hooks/use-status-engine', () => ({ useStatusGraph: () => ({ graph: INBOX_GRAPH }) }));
vi.mock('@/hooks/use-my-teams', () => ({ useMyTeams: () => ({ teams: INBOX_TEAMS }) }));
vi.mock('@/hooks/use-teams', () => ({
  useTeams: () => ({ teams: [...INBOX_TEAMS, { id: 'team-2', name: 'Support team' }] }),
}));
const wide = vi.hoisted(() => ({ value: true }));
vi.mock('@/hooks/use-media-query', () => ({ useMediaQuery: () => wide.value }));
vi.mock('@/components/platform/conversation-drawer', async () => {
  const actual = await vi.importActual<typeof import('@/components/platform/conversation-drawer')>(
    '@/components/platform/conversation-drawer',
  );
  return {
    ...actual,
    ConversationDrawer: ({ contactId }: { contactId: string | null }) => (
      <div data-testid="conversation-pane-stub">{contactId}</div>
    ),
  };
});

import InboxPage from '../page';
import { InboxFilterBar } from '../components/inbox-filter-bar';
import { InboxViewDialog } from '../components/inbox-view-dialog';
import { InboxViewRail } from '../components/inbox-view-rail';
import { ThreadList } from '../components/thread-list';

/** Parity markup with React 19 `_r_N_` ids renamed and clock times masked. */
export function stableInbox(root: Element): string {
  const seen = new Map<string, string>();
  return parityHtml(root)
    .replace(/_r_[0-9a-z]+_/g, (id) => {
      let s = seen.get(id);
      if (!s) {
        s = `_rid${seen.size}_`;
        seen.set(id, s);
      }
      return s;
    })
    .replace(/\b\d{1,2}:\d{2}(?::\d{2})?(?:[\s ]?[AaPp]\.?[Mm]\.?)?/g, 'HH:MM')
    .replace(/ style="[^"]*(?:opacity|transform)[^"]*"/g, ' style="(animating)"');
}

const noop = () => undefined;

describe('inbox switch-off parity', () => {
  beforeEach(() => {
    expect(Date.now()).toBe(INBOX_NOW.getTime());
    window.history.replaceState(null, '', '/omnichannel/inbox');
    listThreads.mockReset();
    listThreads.mockResolvedValue(INBOX_THREADS);
    wide.value = true;
  });

  it('page at desktop width: rail, filters, list and pane', async () => {
    window.history.replaceState(null, '', '/omnichannel/inbox?thread=cnt-001');
    const { container } = render(<InboxPage />);
    await screen.findByTestId('thread-row-cnt-003');
    expect(stableInbox(container)).toMatchSnapshot();
  });

  it('page at phone width: the list pane', async () => {
    wide.value = false;
    const { container } = render(<InboxPage />);
    await screen.findByTestId('thread-row-cnt-003');
    expect(stableInbox(container)).toMatchSnapshot();
  });

  it('page at phone width: an opened conversation', async () => {
    wide.value = false;
    const user = userEvent.setup();
    const { container } = render(<InboxPage />);
    await user.click(await screen.findByTestId('thread-row-cnt-002'));
    await waitFor(() => expect(screen.getByTestId('conversation-pane-stub')).toHaveTextContent('cnt-002'));
    expect(stableInbox(container)).toMatchSnapshot();
  });

  it('thread list: rows, loading, empty and error', () => {
    const base = {
      filters: DEFAULT_FILTERS,
      setFilters: noop,
      onSelect: noop,
    };
    const rows = render(
      <ThreadList {...base} threads={INBOX_THREADS} isLoading={false} error={null} selectedId="cnt-002" />,
    );
    expect(stableInbox(rows.container)).toMatchSnapshot('rows');
    rows.unmount();
    const loading = render(<ThreadList {...base} threads={[]} isLoading error={null} selectedId={null} />);
    expect(stableInbox(loading.container)).toMatchSnapshot('loading');
    loading.unmount();
    const empty = render(<ThreadList {...base} threads={[]} isLoading={false} error={null} selectedId={null} />);
    expect(stableInbox(empty.container)).toMatchSnapshot('empty');
    empty.unmount();
    const failed = render(
      <ThreadList {...base} threads={[]} isLoading={false} error="Could not load conversations" selectedId={null} />,
    );
    expect(stableInbox(failed.container)).toMatchSnapshot('error');
  });

  it('filter bar: defaults and with choices made', () => {
    const plain = render(<InboxFilterBar filters={DEFAULT_FILTERS} setFilters={noop} />);
    expect(stableInbox(plain.container)).toMatchSnapshot('defaults');
    plain.unmount();
    const chosen = render(
      <InboxFilterBar
        filters={{ ...DEFAULT_FILTERS, status: 'OPEN', sort: 'oldest', priority: 'URGENT', unreplied: true }}
        setFilters={noop}
      />,
    );
    expect(stableInbox(chosen.container)).toMatchSnapshot('chosen');
  });

  it('view rail: sidebar and select', () => {
    const sidebar = render(
      <InboxViewRail
        workspaceId="wsp-001"
        filters={{ ...DEFAULT_FILTERS, viewId: 'view-1' }}
        setFilters={noop}
        variant="sidebar"
      />,
    );
    expect(stableInbox(sidebar.container)).toMatchSnapshot('sidebar');
    sidebar.unmount();
    const select = render(
      <InboxViewRail workspaceId="wsp-001" filters={DEFAULT_FILTERS} setFilters={noop} variant="select" />,
    );
    expect(stableInbox(select.container)).toMatchSnapshot('select');
  });

  it('save-view dialog: create and rename', () => {
    const create = render(
      <InboxViewDialog open onOpenChange={noop} view={null} canShare onCreate={vi.fn()} onUpdate={vi.fn()} />,
    );
    expect(stableInbox(document.body)).toMatchSnapshot('create');
    create.unmount();
    render(
      <InboxViewDialog
        open
        onOpenChange={noop}
        view={INBOX_VIEWS[0]}
        canShare={false}
        onCreate={vi.fn()}
        onUpdate={vi.fn()}
      />,
    );
    expect(stableInbox(document.body)).toMatchSnapshot('rename');
  });
});
