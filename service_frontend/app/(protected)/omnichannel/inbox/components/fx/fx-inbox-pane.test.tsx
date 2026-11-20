/**
 * The inbox with the Foundryx UIUX switch ON and the real conversation pane
 * (slice W1-INBOX): the pane's red action ("Close conversation") sits in the
 * inbox's slim page header, never twice, and hides while the close dialog is
 * open. Runs on the mock conversation service.
 */
import type { ReactNode } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { INBOX_GRAPH } from '../../__parity__/inbox-fixtures';
import InboxPage from '../../page';

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    status: 'authenticated',
    data: {
      user: {
        id: 'usr-demo',
        name: 'Demo User',
        timezone: 'Asia/Kuala_Lumpur',
        permissions: [
          'conversations.read',
          'conversations.reply',
          'conversations.assign',
        ],
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
vi.mock('@/services/conversation-service', async () => {
  const { mockConversationService } =
    await import('@/services/conversation-service.mock');
  return { conversationService: mockConversationService };
});
vi.mock('@/services/workspace-service', () => ({
  workspaceService: {
    list: vi.fn(async () => ({ data: [{ id: 'wsp-001', isDefault: true }] })),
    getMembers: vi.fn(async () => [
      { userId: 'usr-demo', name: 'Demo User', email: 'demo@example.com' },
    ]),
  },
}));
vi.mock('@/hooks/use-conversation-socket', () => ({
  useConversationSocket: () => undefined,
}));
vi.mock('@/hooks/use-workspace-has-active-channel', () => ({
  useWorkspaceHasActiveChannel: () => true,
}));
vi.mock('@/hooks/use-thread-events', () => ({
  useThreadEvents: () => ({ events: [], reload: vi.fn(async () => undefined) }),
}));
vi.mock('@/hooks/use-close-reasons', () => ({
  useCloseReasons: () => ({
    reasons: [{ id: 'cr-1', name: 'Resolved', isActive: true, sortOrder: 1 }],
  }),
}));
vi.mock('@/hooks/use-teams', () => ({ useTeams: () => ({ teams: [] }) }));
vi.mock('@/hooks/use-my-teams', () => ({ useMyTeams: () => ({ teams: [] }) }));
vi.mock('@/hooks/use-shortcuts', () => ({
  useShortcuts: () => ({ shortcuts: [], isRunning: false, run: vi.fn() }),
}));
vi.mock('@/hooks/use-contact-fields', () => ({
  useContactFields: () => ({ fields: [] }),
}));
vi.mock('@/hooks/use-contact-tags', () => ({
  useContactTags: () => ({ tags: [] }),
}));
vi.mock('@/hooks/use-inbox-views', () => ({
  useInboxViews: () => ({
    views: [],
    create: vi.fn(),
    update: vi.fn(),
    refresh: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-status-engine', () => ({
  useStatusGraph: () => ({ graph: INBOX_GRAPH }),
}));
vi.mock('@/hooks/use-media-query', () => ({ useMediaQuery: () => true }));

function header(): HTMLElement {
  return document.querySelector('[data-fx-header]') as HTMLElement;
}

describe('the pane red action in the inbox header', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/omnichannel/inbox');
    resetPageActionsForTests();
  });

  it('registers Close conversation in the page header, once, and hides it while the close dialog is open', async () => {
    const user = userEvent.setup();
    render(
      <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
        <InboxPage />
      </FxProvider>,
    );
    // Nothing open: the header carries no red action.
    await screen.findByTestId('thread-row-cnt-001', {}, { timeout: 3000 });
    expect(
      within(header()).queryByRole('button', { name: /Close/ }),
    ).toBeNull();

    await user.click(screen.getByTestId('thread-row-cnt-001'));
    const action = await within(header()).findByRole(
      'button',
      { name: /Close Sarah/ },
      { timeout: 3000 },
    );
    // Never twice: the pane does not draw its own copy.
    expect(screen.getAllByRole('button', { name: /Close Sarah/ })).toHaveLength(
      1,
    );

    await user.click(action);
    await screen.findByRole('dialog');
    await waitFor(() =>
      expect(
        within(header()).queryByRole('button', { name: /Close Sarah/ }),
      ).toBeNull(),
    );

    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(
      await within(header()).findByRole('button', { name: /Close Sarah/ }),
    ).toBeInTheDocument();
  }, 20_000);
});
