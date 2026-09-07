/**
 * Mock web chat VISITOR service (plan 34 / A7b S4). Tunes the panel's
 * loading / empty / populated / sending / failed / offline states with no
 * backend (AC-WEB-10). Sessions are keyed by the OPAQUE token itself (a
 * fresh session mints `mock-visitor-token:<uuid>`) rather than a widget key
 * -> session map, so a stored-token replay (AC-WEB-29/49/50) behaves exactly
 * like the real JWT: present the same token back, get the same visitor/
 * contact/history back.
 */
import type {
  PostVisitorMessageInput,
  VisitorMessage,
  VisitorMessagesPage,
  WebchatSessionResult,
} from '@/types/omnichannel';
import { delay } from './mock-query';
import type { WebchatVisitorService } from './webchat-visitor-service';

const MOCK_WORKSPACE_ID = 'ws-demo-001';
const MOCK_WIDGET_KEY = 'wk_demo0000000000000000000001';

interface MockSession {
  visitorId: string;
  contactId: string | null;
  messages: VisitorMessage[];
}

const sessions = new Map<string, MockSession>();

function newId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

function defaultSessionResult(token: string, session: MockSession): WebchatSessionResult {
  return {
    token,
    expiresAt: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(),
    visitorId: session.visitorId,
    workspaceId: MOCK_WORKSPACE_ID,
    config: {
      appearance: {
        accentColor: '#FF5A00',
        position: 'right',
        headerTitle: 'Chat with us',
        agentDisplayName: 'Support',
      },
      greeting: 'Hi! How can we help you today?',
      offlineGreeting: "We're offline right now - leave a message and we'll reply.",
      preChat: { askName: true, askEmail: true, askPhone: false },
      agentDisplayName: 'Support',
      tenantName: null,
      brandTokens: {},
    },
    online: true,
    messages: session.messages,
  };
}

export const mockWebchatVisitorService: WebchatVisitorService = {
  async startSession(_widgetKey: string, token: string | null): Promise<WebchatSessionResult> {
    const existing = token ? sessions.get(token) : undefined;
    const key: string = token && existing ? token : `mock-visitor-token:${newId('tok')}`;
    const session: MockSession = existing ?? { visitorId: newId('visitor'), contactId: null, messages: [] };
    if (!existing) sessions.set(key, session);
    return delay(defaultSessionResult(key, session), 300);
  },

  async sendMessage(
    _widgetKey: string,
    token: string,
    input: PostVisitorMessageInput,
  ): Promise<VisitorMessage | null> {
    if ((input.hp ?? '').trim()) return delay(null, 150); // honeypot - AC-WEB-32
    const session = sessions.get(token);
    if (!session) throw new Error('Session not found');
    if (!session.contactId) session.contactId = newId('contact'); // lazy creation, D-A7B-7

    const message: VisitorMessage = {
      id: newId('msg'),
      direction: 'in',
      text: input.text,
      media: null,
      quickReplies: null,
      agentName: null,
      createdAt: new Date().toISOString(),
      status: null,
    };
    session.messages.push(message);

    // A canned agent reply, mirroring the mock inbox's own auto-reply
    // pattern - gives S4's Sent/populated states something to render without
    // a real agent in the loop.
    const reply: VisitorMessage = {
      id: newId('msg'),
      direction: 'out',
      text: 'Thanks for reaching out! Someone from our team will be with you shortly.',
      media: null,
      quickReplies: [
        { id: 'q1', title: 'Pricing' },
        { id: 'q2', title: 'Support' },
      ],
      agentName: 'Support',
      createdAt: new Date(Date.now() + 400).toISOString(),
      status: 'sent',
    };
    setTimeout(() => session!.messages.push(reply), 500);

    return delay(message, 250);
  },

  async listMessages(
    _widgetKey: string,
    token: string,
    after?: string | null,
  ): Promise<VisitorMessagesPage> {
    const session = sessions.get(token);
    if (!session) return delay({ data: [], nextAfter: null }, 150);
    const startIndex = after ? session.messages.findIndex((m) => m.id === after) + 1 : 0;
    return delay({ data: session.messages.slice(startIndex), nextAfter: null }, 150);
  },

  subscribe(): () => void {
    // The mock transport has no server to push from - the hook's poll
    // fallback (D-A7B-16) is what surfaces the canned agent reply above.
    return () => {};
  },
};

export function __mockWebchatWidgetKey(): string {
  return MOCK_WIDGET_KEY;
}
