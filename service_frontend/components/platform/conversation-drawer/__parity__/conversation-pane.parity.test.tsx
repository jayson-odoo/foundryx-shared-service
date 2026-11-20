/**
 * Switch-off parity for the conversation pane (Foundryx UIUX slice W1-CONV,
 * build plan 1.3 and 4): the pane used by the inbox and by the contact
 * record's Conversation tab, rendered with the switch OFF. Covers the pane
 * (open window, closed window, snoozed, no channel, compact, nothing open),
 * the composer, the message bubbles, the close dialog and the activities feed.
 * Recorded on the code as it was before the slice; a change that needs one of
 * these snapshots updated is wrong by definition (fix the code, never the
 * snapshot). Generated ids are renamed in order of appearance and clock times
 * are masked, so the snapshots hold markup only.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import type {
  ConversationEvent,
  ConversationMessage,
  QuickReply,
  WhatsAppTemplate,
} from '@/types/omnichannel';

// The mock service seeds its threads relative to "now": pin the clock before
// any module is loaded so the seeded windows and day lines never move.
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
        permissions: [
          'conversations.read',
          'conversations.reply',
          'conversations.assign',
          'conversations.shortcut',
          'contacts.manage',
          'teams.read',
        ],
      },
    },
  }),
  getSession: vi.fn(async () => null),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/conversation-service', async () => {
  const { mockConversationService } = await import('@/services/conversation-service.mock');
  return { conversationService: mockConversationService };
});
vi.mock('@/services/workspace-service', () => ({
  workspaceService: {
    getMembers: vi.fn(async () => [
      { userId: 'usr-demo', name: 'Demo User', email: 'demo@example.com' },
      { userId: 'usr-kay', name: 'Kay Tan', email: 'kay@example.com' },
    ]),
  },
}));
vi.mock('@/hooks/use-conversation-socket', () => ({ useConversationSocket: () => undefined }));
const hasChannel = { value: true as boolean | null };
vi.mock('@/hooks/use-workspace-has-active-channel', () => ({
  useWorkspaceHasActiveChannel: () => hasChannel.value,
}));
const EVENTS: ConversationEvent[] = [];
vi.mock('@/hooks/use-thread-events', () => ({
  useThreadEvents: () => ({ events: EVENTS, reload: vi.fn(async () => undefined) }),
}));
vi.mock('@/hooks/use-close-reasons', () => ({
  useCloseReasons: () => ({
    reasons: [
      { id: 'cr-1', name: 'Resolved', isActive: true, sortOrder: 1 },
      { id: 'cr-2', name: 'No reply', isActive: true, sortOrder: 2 },
    ],
  }),
}));
vi.mock('@/hooks/use-teams', () => ({
  useTeams: () => ({ teams: [{ id: 'team-1', name: 'Sales team', isActive: true }] }),
}));
vi.mock('@/hooks/use-my-teams', () => ({ useMyTeams: () => ({ teams: [] }) }));
vi.mock('@/hooks/use-shortcuts', () => ({
  useShortcuts: () => ({
    shortcuts: [{ workflowId: 'wf-1', name: 'Send price list' }],
    isRunning: false,
    run: vi.fn(),
  }),
}));
const wide = { value: true };
vi.mock('@/hooks/use-media-query', () => ({ useMediaQuery: () => wide.value }));
vi.mock('@/hooks/use-contact-fields', () => ({ useContactFields: () => ({ fields: [] }) }));
vi.mock('@/hooks/use-contact-tags', () => ({ useContactTags: () => ({ tags: [] }) }));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => '/omnichannel/inbox',
  useSearchParams: () => new URLSearchParams(),
}));

import { ActivityFeed } from '../activity-feed';
import { CloseThreadDialog } from '../close-thread-dialog';
import { Composer } from '../composer';
import { ConversationDrawer } from '../conversation-drawer';
import { MessageBubble } from '../message-bubble';

/** Parity markup with React 19 `_r_N_` ids renamed and clock times masked. */
function stable(root: Element): string {
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
    .replace(/\b\d{1,2}:\d{2}(?::\d{2})?(?:[\s ]?[AaPp]\.?[Mm]\.?)?/g, 'HH:MM')
    // Enter animations leave mid-flight opacity/transform styles behind.
    .replace(/ style="[^"]*(?:opacity|transform)[^"]*"/g, ' style="(animating)"');
}

function msg(over: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: 'msg-1',
    contactId: 'cnt-001',
    channelId: 'chn-001',
    senderType: 'CONTACT',
    senderId: null,
    senderName: null,
    messageType: 'TEXT',
    body: 'Hello there',
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
    createdAt: '2026-06-04T10:00:00Z',
    ...over,
  };
}

const TEMPLATES: WhatsAppTemplate[] = [
  {
    id: 'tpl-1',
    channelId: 'chn-001',
    name: 'booking_update',
    language: 'en',
    category: 'UTILITY',
    status: 'APPROVED',
    bodyText: 'Hi {{1}}, update: {{2}}.',
    variableCount: 2,
    headerFormat: null,
    headerVariableCount: 0,
    buttonVariableCount: 0,
  },
];
const QUICK: QuickReply[] = [{ id: 'qr-1', workspaceId: 'wsp-001', shortcut: '/hi', body: 'Hi! How can I help?' }];

const composerBase = {
  templates: TEMPLATES,
  quickReplies: QUICK,
  isSending: false,
  sendError: null,
  onSend: vi.fn(async () => true),
  onSendTemplate: vi.fn(async () => true),
  onSendMedia: vi.fn(async () => true),
  onSendInteractive: vi.fn(async () => true),
  onSendLocation: vi.fn(async () => true),
  onSendContacts: vi.fn(async () => true),
  onAddNote: vi.fn(async () => true),
};

beforeEach(async () => {
  const { __mockResetConversations } = await import('@/services/conversation-service.mock');
  __mockResetConversations();
  Element.prototype.scrollIntoView = vi.fn();
  window.localStorage.clear();
  hasChannel.value = true;
  wide.value = true;
});

afterAll(() => {
  vi.useRealTimers();
});

describe('conversation pane parity (switch off)', () => {
  it('pane: open window, assigned, contact panel closed', async () => {
    const { container } = render(<ConversationDrawer contactId="cnt-001" />);
    await screen.findByTestId('conversation-drawer');
    await waitFor(() => expect(screen.getAllByTestId('bubble-agent').length).toBeGreaterThan(0));
    expect(stable(container)).toMatchSnapshot();
  });

  it('pane: closed 24-hour window', async () => {
    const { container } = render(<ConversationDrawer contactId="cnt-002" />);
    await screen.findByTestId('csw-banner');
    expect(stable(container)).toMatchSnapshot();
  });

  it('pane: snoozed thread shows Reopen', async () => {
    const { container } = render(<ConversationDrawer contactId="cnt-004" />);
    await screen.findByTestId('thread-reopen');
    expect(stable(container)).toMatchSnapshot();
  });

  it('pane: no channel connected', async () => {
    hasChannel.value = false;
    const { container } = render(<ConversationDrawer contactId="cnt-002" />);
    await screen.findByTestId('no-channel-banner');
    expect(stable(container)).toMatchSnapshot();
  });

  it('pane: contact panel open as the right pane', async () => {
    window.localStorage.setItem('omnichannel:contact-panel-open', '1');
    const { container } = render(<ConversationDrawer contactId="cnt-001" />);
    await screen.findByTestId('contact-panel-pane');
    expect(stable(container)).toMatchSnapshot();
  });

  it('pane: compact (contact record tab)', async () => {
    const { container } = render(<ConversationDrawer contactId="cnt-001" compact />);
    await screen.findByTestId('conversation-drawer');
    await waitFor(() => expect(screen.getAllByTestId('bubble-agent').length).toBeGreaterThan(0));
    expect(stable(container)).toMatchSnapshot();
  });

  it('pane: nothing open', () => {
    const { container } = render(<ConversationDrawer contactId={null} />);
    expect(stable(container)).toMatchSnapshot();
  });

  it('composer: open window, closed window, note mode, no channel, reply strip, send error', () => {
    const { container, rerender } = render(<Composer {...composerBase} windowOpen />);
    const out: string[] = [stable(container)];
    rerender(<Composer {...composerBase} windowOpen={false} />);
    out.push(stable(container));
    rerender(<Composer {...composerBase} windowOpen={false} mode="note" />);
    out.push(stable(container));
    rerender(<Composer {...composerBase} windowOpen={false} noChannel />);
    out.push(stable(container));
    rerender(
      <Composer
        {...composerBase}
        windowOpen
        sendError="The message could not be sent."
        replyTo={msg({ body: 'Can I change my booking?' })}
        onCancelReply={vi.fn()}
      />,
    );
    out.push(stable(container));
    expect(out).toMatchSnapshot();
  });

  it('bubbles: contact, agent in every delivery state, failed, note, template, reply', () => {
    const { container } = render(
      <div>
        <MessageBubble message={msg()} contactName="Sarah Chen" />
        <MessageBubble message={msg({ id: 'a0', senderType: 'AGENT', deliveryStatus: null })} />
        <MessageBubble message={msg({ id: 'a1', senderType: 'AGENT', deliveryStatus: 'QUEUED' })} />
        <MessageBubble message={msg({ id: 'a2', senderType: 'AGENT', deliveryStatus: 'SENT' })} />
        <MessageBubble message={msg({ id: 'a3', senderType: 'AGENT', deliveryStatus: 'DELIVERED' })} />
        <MessageBubble message={msg({ id: 'a4', senderType: 'AGENT', deliveryStatus: 'READ' })} />
        <MessageBubble
          message={msg({ id: 'a5', senderType: 'AGENT', deliveryStatus: 'FAILED', errorMessage: 'Window closed.' })}
        />
        <MessageBubble message={msg({ id: 's1', senderType: 'SYSTEM', senderName: 'Demo User', body: 'VIP client' })} />
        <MessageBubble
          message={msg({ id: 't1', senderType: 'AGENT', messageType: 'TEMPLATE', deliveryStatus: 'SENT' })}
        />
        <MessageBubble
          message={msg({
            id: 'r1',
            senderType: 'AGENT',
            deliveryStatus: 'READ',
            replyTo: { id: 'msg-1', senderType: 'CONTACT', senderName: null, body: 'Hello there' },
            reactions: [{ emoji: '👍', reactorType: 'CONTACT', reactor: 'CONTACT' }],
          })}
          contactName="Sarah Chen"
          highlight="hello"
          isActiveMatch
        />
      </div>,
    );
    expect(stable(container)).toMatchSnapshot();
  });

  it('close dialog: open', async () => {
    render(
      <CloseThreadDialog
        open
        onOpenChange={vi.fn()}
        reasons={[
          { id: 'cr-1', workspaceId: 'wsp-001', name: 'Resolved', isActive: true, sortOrder: 1 },
          { id: 'cr-2', workspaceId: 'wsp-001', name: 'Old', isActive: false, sortOrder: 2 },
        ] as never}
        onClose={vi.fn(async () => undefined)}
      />,
    );
    await screen.findByTestId('close-thread-submit');
    expect(stable(document.body)).toMatchSnapshot();
  });

  it('activities feed: notes and events, and empty', () => {
    const events = [
      {
        id: 'ev-1',
        eventType: 'assigned',
        actorName: 'Demo User',
        toLabel: 'Kay Tan',
        fromLabel: null,
        closeReasonName: null,
        createdAt: '2026-06-04T09:00:00Z',
      },
      {
        id: 'ev-2',
        eventType: 'closed',
        actorName: 'Kay Tan',
        toLabel: null,
        fromLabel: null,
        closeReasonName: 'Resolved',
        createdAt: '2026-06-05T07:00:00Z',
      },
    ] as unknown as ConversationEvent[];
    const formatTime = (iso: string) => iso.slice(11, 16);
    const { container, rerender } = render(
      <ActivityFeed
        messages={[msg({ id: 's1', senderType: 'SYSTEM', senderName: 'Demo User', body: 'VIP client' })]}
        events={events}
        contactName="Sarah Chen"
        formatTime={formatTime}
        timeZone="Asia/Kuala_Lumpur"
      />,
    );
    const out = [stable(container)];
    rerender(<ActivityFeed messages={[]} events={[]} contactName="Sarah Chen" formatTime={formatTime} />);
    out.push(stable(container));
    expect(out).toMatchSnapshot();
  });
});
