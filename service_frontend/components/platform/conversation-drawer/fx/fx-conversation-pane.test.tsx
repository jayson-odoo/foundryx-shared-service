/**
 * The conversation pane with the Foundryx UIUX switch ON (slice W1-CONV):
 * the red action and its full label (in the pane, or handed to the page
 * header), the done toasts with and without Undo, the "New messages" pill,
 * the 24-hour window strip, the kept draft and the delivery states.
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
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  ConversationMessage,
  ConversationThread,
  WhatsAppTemplate,
} from '@/types/omnichannel';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import {
  resetPageActionsForTests,
  usePageActions,
} from '@/components/fx/actions/page-actions-context';
import { Composer } from '../composer';
import { ConversationDrawer } from '../conversation-drawer';
import { MessageBubble } from '../message-bubble';
import { fxConversationOf } from './fx-close-thread-dialog';
import { fxWindowLine } from './fx-composer';
import { fxDeliveryLabel } from './fx-message-bubble';

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    status: 'authenticated',
    data: {
      user: {
        id: 'usr-me',
        name: 'Jayden',
        timezone: 'Asia/Kuala_Lumpur',
        permissions: [
          'conversations.read',
          'conversations.reply',
          'conversations.assign',
          'teams.read',
        ],
      },
    },
  }),
  getSession: vi.fn(async () => null),
}));
vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
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

const toastMock = vi.hoisted(() => ({
  fxDone: vi.fn(),
  error: vi.fn(),
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  custom: vi.fn(),
  dismiss: vi.fn(),
  message: vi.fn(),
}));
vi.mock('@/lib/toast', () => ({ toast: toastMock }));

vi.mock('@/services/conversation-service', () => ({
  conversationService: {
    listTemplates: vi.fn(async () => []),
    listQuickReplies: vi.fn(async () => []),
  },
}));
vi.mock('@/services/workspace-service', () => ({
  workspaceService: {
    getMembers: vi.fn(async () => [
      { userId: 'usr-kay', name: 'Kay Tan', email: 'kay@example.com' },
    ]),
  },
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
vi.mock('@/hooks/use-media-query', () => ({ useMediaQuery: () => true }));
vi.mock('@/hooks/use-contact-fields', () => ({
  useContactFields: () => ({ fields: [] }),
}));
vi.mock('@/hooks/use-contact-tags', () => ({
  useContactTags: () => ({ tags: [] }),
}));

function msg(over: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: 'm1',
    contactId: 'cnt-1',
    channelId: 'chn-1',
    senderType: 'CONTACT',
    senderId: null,
    senderName: null,
    messageType: 'TEXT',
    body: 'Hello',
    mediaUrl: null,
    mediaMime: null,
    mediaFilename: null,
    mediaSize: null,
    voice: false,
    payload: null,
    reactions: [],
    externalMessageId: null,
    deliveryStatus: null,
    errorCode: null,
    errorMessage: null,
    replyTo: null,
    createdAt: '2026-11-18T01:00:00Z',
    ...over,
  };
}

function threadOf(over: Partial<ConversationThread> = {}): ConversationThread {
  return {
    id: 'cnt-1',
    tenantId: 't',
    workspaceId: 'wsp-1',
    name: 'Lim Wei Jie',
    firstName: 'Lim',
    lastName: 'Wei Jie',
    phone: '+60 12-345 6789',
    email: null,
    language: null,
    countryCode: null,
    avatarUrl: null,
    assignedUserId: 'usr-me',
    assignedUserName: 'Jayden',
    assignedTeamId: null,
    assignedTeamName: null,
    status: 'OPEN',
    priority: 'MEDIUM',
    channelId: 'chn-1',
    channelType: 'WHATSAPP',
    cswExpiresAt: '2099-01-01T00:00:00Z',
    windowExpiresAt: '2099-01-01T00:00:00Z',
    humanAgentExpiresAt: null,
    lastIncomingMessageAt: null,
    lastMessageAt: null,
    lastMessagePreview: null,
    unreadCount: 0,
    customFields: {},
    tags: [],
    lifecycle: null,
    createdAt: '2026-11-01T00:00:00Z',
    ...over,
  } as ConversationThread;
}

// A controllable `useMessages`: tests change `state` and re-render.
const state = vi.hoisted(() => ({ current: {} as Record<string, unknown> }));
vi.mock('@/hooks/use-messages', () => ({ useMessages: () => state.current }));

function resetState(
  thread: ConversationThread,
  messages: ConversationMessage[],
) {
  state.current = {
    thread,
    messages,
    isLoading: false,
    error: null,
    erased: false,
    isSending: false,
    sendError: null,
    send: vi.fn(async () => true),
    sendTemplate: vi.fn(async () => true),
    sendMedia: vi.fn(async () => true),
    sendInteractive: vi.fn(async () => true),
    sendLocation: vi.fn(async () => true),
    sendContacts: vi.fn(async () => true),
    react: vi.fn(async () => true),
    addNote: vi.fn(async () => true),
    assign: vi.fn(async () => undefined),
    assignToMe: vi.fn(async () => undefined),
    assignTeam: vi.fn(async () => undefined),
    setStatus: vi.fn(async () => undefined),
    setPriority: vi.fn(async () => undefined),
    closeThread: vi.fn(async () => thread),
    patchContact: vi.fn(async () => thread),
    moveLifecycle: vi.fn(async () => thread),
  };
}
const fn = (name: string) => state.current[name] as ReturnType<typeof vi.fn>;

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}

function HeaderProbe() {
  const page = usePageActions();
  return (
    <output data-testid="probe">
      {page.hidden ? '' : (page.main?.fullLabel ?? '')}
    </output>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  resetPageActionsForTests();
  window.localStorage.clear();
  Element.prototype.scrollIntoView = vi.fn();
  resetState(threadOf(), [msg()]);
});

describe('red action', () => {
  it('names the conversation in full and opens the close dialog', async () => {
    render(
      <On>
        <ConversationDrawer contactId="cnt-1" />
        <HeaderProbe />
      </On>,
    );
    const red = await screen.findByRole('button', {
      name: "Close Lim Wei Jie's conversation",
    });
    expect(red).toHaveTextContent('Close conversation');
    // Drawn in the pane, so not handed to a page header (never twice).
    expect(screen.getByTestId('probe')).toHaveTextContent('');
    await userEvent.click(red);
    expect(await screen.findByRole('dialog')).toHaveTextContent(
      "Close Lim Wei Jie's conversation?",
    );
    expect(
      screen.getByRole('button', { name: 'Keep it open' }),
    ).toBeInTheDocument();
  });

  it('is handed to the page header when the host draws one, and hidden while the dialog is open', async () => {
    render(
      <On>
        <ConversationDrawer contactId="cnt-1" fxPageHeader />
        <HeaderProbe />
      </On>,
    );
    await waitFor(() =>
      expect(screen.getByTestId('probe')).toHaveTextContent(
        "Close Lim Wei Jie's conversation",
      ),
    );
    expect(
      screen.queryByRole('button', {
        name: "Close Lim Wei Jie's conversation",
      }),
    ).not.toBeInTheDocument();
  });

  it('is not registered in compact mode', async () => {
    render(
      <On>
        <ConversationDrawer contactId="cnt-1" compact fxPageHeader />
        <HeaderProbe />
      </On>,
    );
    await screen.findByTestId('conversation-drawer');
    expect(screen.getByTestId('probe')).toHaveTextContent('');
    expect(
      screen.queryByRole('button', { name: /conversation$/ }),
    ).not.toBeInTheDocument();
  });

  it('becomes Reopen once snoozed, with an Undo that snoozes again', async () => {
    resetState(threadOf({ status: 'SNOOZED' }), [msg()]);
    render(
      <On>
        <ConversationDrawer contactId="cnt-1" />
      </On>,
    );
    await userEvent.click(
      await screen.findByRole('button', {
        name: "Reopen Lim Wei Jie's conversation",
      }),
    );
    await waitFor(() => expect(toastMock.fxDone).toHaveBeenCalled());
    expect(fn('setStatus')).toHaveBeenCalledWith('OPEN');
    const input = toastMock.fxDone.mock.calls[0][0];
    expect(input).toMatchObject({
      what: "Lim Wei Jie's conversation reopened",
      byWhom: 'Jayden',
    });
    input.undo();
    expect(fn('setStatus')).toHaveBeenLastCalledWith('SNOOZED');
  });

  it('reopening a closed conversation toasts without Undo (closing needs a reason)', async () => {
    resetState(threadOf({ status: 'CLOSED' }), [msg()]);
    render(
      <On>
        <ConversationDrawer contactId="cnt-1" />
      </On>,
    );
    await userEvent.click(
      await screen.findByRole('button', {
        name: "Reopen Lim Wei Jie's conversation",
      }),
    );
    await waitFor(() => expect(toastMock.fxDone).toHaveBeenCalled());
    expect(toastMock.fxDone.mock.calls[0][0].undo).toBeUndefined();
  });
});

describe('done toasts', () => {
  it('snooze toasts what and by whom; Undo puts it back to open', async () => {
    render(
      <On>
        <ConversationDrawer contactId="cnt-1" />
      </On>,
    );
    await userEvent.click(
      await screen.findByRole('button', { name: 'Snooze' }),
    );
    expect(fn('setStatus')).toHaveBeenCalledWith('SNOOZED');
    await waitFor(() => expect(toastMock.fxDone).toHaveBeenCalled());
    const input = toastMock.fxDone.mock.calls[0][0];
    expect(input).toMatchObject({
      what: "Lim Wei Jie's conversation snoozed",
      byWhom: 'Jayden',
    });
    input.undo();
    expect(fn('setStatus')).toHaveBeenLastCalledWith('OPEN');
  });

  it('close toasts the reason; Undo reopens', async () => {
    render(
      <On>
        <ConversationDrawer contactId="cnt-1" />
      </On>,
    );
    await userEvent.click(
      await screen.findByRole('button', {
        name: "Close Lim Wei Jie's conversation",
      }),
    );
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(
      within(dialog).getByRole('combobox', { name: 'Close reason' }),
    );
    await userEvent.click(
      await screen.findByRole('option', { name: 'Resolved' }),
    );
    await userEvent.click(within(dialog).getByTestId('close-thread-submit'));
    await waitFor(() => expect(toastMock.fxDone).toHaveBeenCalled());
    expect(fn('closeThread')).toHaveBeenCalledWith({
      closeReasonId: 'cr-1',
      note: undefined,
    });
    const input = toastMock.fxDone.mock.calls[0][0];
    expect(input.what).toBe("Lim Wei Jie's conversation closed as Resolved");
    // The dialog itself no longer toasts "Conversation closed."
    expect(toastMock.success).not.toHaveBeenCalled();
    input.undo();
    expect(fn('setStatus')).toHaveBeenLastCalledWith('OPEN');
  });

  it('assign toasts to whom; Undo restores the previous owner and team', async () => {
    resetState(
      threadOf({ assignedUserId: 'usr-me', assignedTeamId: 'team-9' }),
      [msg()],
    );
    render(
      <On>
        <ConversationDrawer contactId="cnt-1" />
      </On>,
    );
    await userEvent.click(
      await screen.findByRole('button', { name: 'Assign' }),
    );
    await userEvent.click(
      await screen.findByRole('menuitem', { name: 'Kay Tan' }),
    );
    expect(fn('assign')).toHaveBeenCalledWith('usr-kay');
    await waitFor(() => expect(toastMock.fxDone).toHaveBeenCalled());
    const input = toastMock.fxDone.mock.calls[0][0];
    expect(input).toMatchObject({
      what: 'Lim Wei Jie assigned to Kay Tan',
      byWhom: 'Jayden',
    });
    input.undo();
    expect(fn('patchContact')).toHaveBeenCalledWith({
      assignedTeamId: 'team-9',
      assignedUserId: 'usr-me',
    });
  });

  it('a failed action shows the error and no done toast', async () => {
    render(
      <On>
        <ConversationDrawer contactId="cnt-1" />
      </On>,
    );
    fn('setStatus').mockRejectedValueOnce(new Error('Conflict'));
    await userEvent.click(
      await screen.findByRole('button', { name: 'Snooze' }),
    );
    await waitFor(() =>
      expect(toastMock.error).toHaveBeenCalledWith('Conflict'),
    );
    expect(toastMock.fxDone).not.toHaveBeenCalled();
  });
});

describe('"New messages" pill', () => {
  beforeEach(() => {
    // jsdom does not scroll: make scrollTo move scrollTop like a browser.
    Element.prototype.scrollTo = function scrollTo(
      this: Element,
      opts?: ScrollToOptions | number,
    ) {
      if (typeof opts === 'object' && opts?.top !== undefined)
        this.scrollTop = opts.top;
    } as Element['scrollTo'];
  });

  function scrollTo(el: HTMLElement, top: number) {
    Object.defineProperty(el, 'scrollHeight', {
      configurable: true,
      value: 2000,
    });
    Object.defineProperty(el, 'clientHeight', {
      configurable: true,
      value: 500,
    });
    el.scrollTop = top;
    fireEvent.scroll(el);
  }

  it('shows only while scrolled up, and jumps to the newest', async () => {
    const view = () => (
      <On>
        <ConversationDrawer contactId="cnt-1" />
      </On>
    );
    const { rerender } = render(view());
    const scroller = await screen.findByTestId('thread-scroller');

    // At the bottom: a new message follows, no pill.
    scrollTo(scroller, 1500);
    resetState(threadOf(), [msg(), msg({ id: 'm2', body: 'Second' })]);
    rerender(view());
    expect(screen.queryByTestId('new-messages-pill')).not.toBeInTheDocument();

    // Scrolled up: the view stays, the pill shows.
    scrollTo(scroller, 200);
    resetState(threadOf(), [
      msg(),
      msg({ id: 'm2', body: 'Second' }),
      msg({ id: 'm3', body: 'Third' }),
    ]);
    rerender(view());
    expect(scroller.scrollTop).toBe(200);
    const pill = await screen.findByRole('button', { name: 'New messages' });

    await userEvent.click(pill);
    expect(scroller.scrollTop).toBe(2000);
    expect(screen.queryByTestId('new-messages-pill')).not.toBeInTheDocument();
  });

  it("the agent's own send always shows, even when scrolled up", async () => {
    const view = () => (
      <On>
        <ConversationDrawer contactId="cnt-1" />
      </On>
    );
    const { rerender } = render(view());
    const scroller = await screen.findByTestId('thread-scroller');
    scrollTo(scroller, 200);
    resetState(threadOf(), [
      msg(),
      msg({ id: 'temp-1', senderType: 'AGENT', body: 'Mine' }),
    ]);
    rerender(view());
    expect(screen.queryByTestId('new-messages-pill')).not.toBeInTheDocument();
    expect(scroller.scrollTop).toBe(2000);
  });

  it('coming back from Activities starts at the newest message', async () => {
    render(
      <On>
        <ConversationDrawer contactId="cnt-1" />
      </On>,
    );
    const scroller = await screen.findByTestId('thread-scroller');
    scrollTo(scroller, 0);
    await userEvent.click(screen.getByRole('tab', { name: 'Activities' }));
    scrollTo(scroller, 0);
    await userEvent.click(screen.getByRole('tab', { name: 'Messages' }));
    expect(scroller.scrollTop).toBe(2000);
  });
});

const TEMPLATES: WhatsAppTemplate[] = [
  {
    id: 'tpl-1',
    channelId: 'chn-1',
    name: 'booking_update',
    language: 'en',
    category: 'UTILITY',
    status: 'APPROVED',
    bodyText: 'Hi {{1}}',
    variableCount: 1,
    headerFormat: null,
    headerVariableCount: 0,
    buttonVariableCount: 0,
  },
];

describe('composer', () => {
  const base = () => ({
    templates: TEMPLATES,
    quickReplies: [],
    isSending: false,
    sendError: null,
    onSend: vi.fn(async () => true),
    onSendTemplate: vi.fn(async () => true),
  });

  it('closed 24-hour window: a strip with Choose template, and the box greyed', async () => {
    render(
      <On>
        <Composer {...base()} windowOpen={false} />
      </On>,
    );
    const strip = screen.getByTestId('csw-banner');
    expect(strip).toHaveTextContent(
      'The 24-hour window has closed. Only an approved template can be sent.',
    );
    const box = screen.getByTestId('message-input');
    expect(box).toBeDisabled();
    expect(box).toHaveAttribute('placeholder', 'Free-form messages are locked');
    await userEvent.click(
      within(strip).getByRole('button', { name: 'Choose template' }),
    );
    expect(await screen.findByRole('dialog')).toHaveTextContent(
      'Send a template',
    );
  });

  it('open window: no strip, the box is usable', () => {
    render(
      <On>
        <Composer {...base()} windowOpen />
      </On>,
    );
    expect(screen.queryByTestId('csw-banner')).not.toBeInTheDocument();
    expect(screen.getByTestId('message-input')).toBeEnabled();
  });

  it('keeps the text when the send fails, clears it when the send succeeds', async () => {
    const props = base();
    props.onSend.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    render(
      <On>
        <Composer {...props} windowOpen />
      </On>,
    );
    const box = screen.getByTestId('message-input');
    await userEvent.type(box, 'See you Friday');
    await userEvent.keyboard('{Enter}');
    await waitFor(() => expect(props.onSend).toHaveBeenCalledTimes(1));
    expect(box).toHaveValue('See you Friday');
    await userEvent.click(screen.getByRole('button', { name: 'Send message' }));
    await waitFor(() => expect(props.onSend).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(box).toHaveValue(''));
    expect(props.onSend).toHaveBeenLastCalledWith({
      messageType: 'TEXT',
      body: 'See you Friday',
      replyToMessageId: undefined,
    });
  });

  it('a second Enter while the send is on its way sends nothing more', async () => {
    let resolve: (ok: boolean) => void = () => undefined;
    const props = base();
    props.onSend.mockImplementation(
      () => new Promise<boolean>((r) => (resolve = r)),
    );
    render(
      <On>
        <Composer {...props} windowOpen />
      </On>,
    );
    const box = screen.getByTestId('message-input');
    await userEvent.type(box, 'Hi');
    await userEvent.keyboard('{Enter}');
    await userEvent.keyboard('{Enter}');
    expect(props.onSend).toHaveBeenCalledTimes(1);
    await act(async () => resolve(true));
    expect(box).toHaveValue('');
  });

  it('window strip words (pure)', () => {
    expect(fxWindowLine(true, true)).toBe(
      'The 24-hour window has closed. Only an approved template can be sent.',
    );
    expect(fxWindowLine(true, false)).toBe('The messaging window has closed.');
    expect(fxWindowLine(false, true)).toBe(
      'The standard messaging window has closed.',
    );
  });
});

describe('delivery states', () => {
  it('names every state on agent bubbles', () => {
    render(
      <On>
        <MessageBubble message={msg({ id: 'temp-x', senderType: 'AGENT' })} />
        <MessageBubble
          message={msg({
            id: 'a1',
            senderType: 'AGENT',
            deliveryStatus: 'QUEUED',
          })}
        />
        <MessageBubble
          message={msg({
            id: 'a2',
            senderType: 'AGENT',
            deliveryStatus: 'SENT',
          })}
        />
        <MessageBubble
          message={msg({
            id: 'a3',
            senderType: 'AGENT',
            deliveryStatus: 'DELIVERED',
          })}
        />
        <MessageBubble
          message={msg({
            id: 'a4',
            senderType: 'AGENT',
            deliveryStatus: 'READ',
          })}
        />
        <MessageBubble
          message={msg({
            id: 'a5',
            senderType: 'AGENT',
            deliveryStatus: 'FAILED',
            errorMessage: 'Window closed.',
          })}
        />
        <MessageBubble message={msg({ id: 'c1' })} />
      </On>,
    );
    for (const label of [
      'Sending',
      'Queued',
      'Sent',
      'Delivered',
      'Read',
      'Not sent',
    ]) {
      expect(screen.getByRole('img', { name: label })).toBeInTheDocument();
    }
    expect(screen.getAllByTestId('fx-delivery')).toHaveLength(6);
    expect(screen.getByTestId('bubble-error')).toHaveTextContent(
      'Window closed.',
    );
  });

  it('labels (pure)', () => {
    expect(fxDeliveryLabel({ id: 'temp-1', deliveryStatus: null })).toBe(
      'Sending',
    );
    expect(fxDeliveryLabel({ id: 'm-1', deliveryStatus: null })).toBeNull();
    expect(fxConversationOf('Lim Wei Jie')).toBe("Lim Wei Jie's conversation");
    expect(fxConversationOf('James')).toBe("James' conversation");
    expect(fxConversationOf('')).toBe('this conversation');
  });
});
