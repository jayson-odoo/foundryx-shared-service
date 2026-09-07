/**
 * Mock conversation service (Phase A - plan 05).
 *
 * In-memory threads + messages with a timer-driven emitter that simulates the
 * realtime pipeline: inbound `message.created`, delivery-receipt
 * `message.status` ticks (SENT→DELIVERED→READ), and `contact.updated`.
 * CSW enforcement mirrors the backend rule: free-form rejected once
 * `cswExpiresAt` has passed - template-only.
 *
 * Seeds are Date.now()-relative (NOT a fixed epoch) because the CSW lock is a
 * comparison against the real clock in the UI.
 */
import { ApiError } from '@/lib/api-client';
import type {
  CloseThreadInput,
  ConversationEvent,
  ConversationMessage,
  ConversationSocketEvent,
  ConversationThread,
  ContactLifecycleSummary,
  ContactTagRef,
  LifecycleMove,
  PatchContactInput,
  QuickReply,
  SendContactsInput,
  SendInteractiveInput,
  SendLocationInput,
  SendMediaInput,
  SendMessageInput,
  SendTemplateInput,
  ShortcutItem,
  ThreadListQuery,
  ThreadPriority,
  ThreadStatus,
  WhatsAppTemplate,
} from '@/types/omnichannel';
// Type-only circular import (conversation-service binds this mock) - safe in TS.
import type { ConversationService } from './conversation-service';
import { __mockAllContactFields } from './contact-field-service.mock';
import { __mockAllContactTags } from './contact-tag-service.mock';
import { __mockAllCloseReasons, __mockBumpCloseReasonUse } from './close-reason-service.mock';
import { delay } from './mock-query';

// ---------------------------------------------------------------------------
// Plan 25 - lifecycle seed graph (mirrors the backend seed materialized per
// workspace, plan §5.3). The mock enforces the SAME edge graph so the "Move
// to" picker only ever offers a fireable move (foolproof-UI, AC-CDM-18).
// ---------------------------------------------------------------------------

interface MockStage {
  id: string;
  key: string;
  label: string;
  color: string;
  isWon: boolean;
  isLost: boolean;
}

const LIFECYCLE_STAGES: MockStage[] = [
  { id: 'stg-new-lead', key: 'new_lead', label: '🆕 New Lead', color: '#3B82F6', isWon: false, isLost: false },
  { id: 'stg-hot-lead', key: 'hot_lead', label: '🔥 Hot Lead', color: '#F97316', isWon: false, isLost: false },
  { id: 'stg-payment', key: 'payment', label: '💵 Payment', color: '#F59E0B', isWon: false, isLost: false },
  { id: 'stg-customer', key: 'customer', label: '🤩 Customer', color: '#22C55E', isWon: true, isLost: false },
  { id: 'stg-cold-lead', key: 'cold_lead', label: '🧊 Cold Lead', color: '#64748B', isWon: false, isLost: true },
];
const ACTIVE_STAGE_KEYS = ['new_lead', 'hot_lead', 'payment'];

function stageByKey(key: string): MockStage {
  const s = LIFECYCLE_STAGES.find((x) => x.key === key);
  if (!s) throw new Error(`Unknown lifecycle stage "${key}"`);
  return s;
}
function stageById(id: string): MockStage | undefined {
  return LIFECYCLE_STAGES.find((x) => x.id === id);
}
function toLifecycleSummary(stage: MockStage): ContactLifecycleSummary {
  return { statusId: stage.id, key: stage.key, label: stage.label, color: stage.color, isWon: stage.isWon, isLost: stage.isLost };
}
/** Fireable outgoing edges from `fromKey` - won (`customer`) is terminal (no
 *  outgoing edges); lost (`cold_lead`) only re-opens to New Lead. */
function movesFrom(fromKey: string): LifecycleMove[] {
  let targetKeys: string[] = [];
  if (ACTIVE_STAGE_KEYS.includes(fromKey)) {
    targetKeys = [...ACTIVE_STAGE_KEYS.filter((k) => k !== fromKey), 'customer', 'cold_lead'];
  } else if (fromKey === 'cold_lead') {
    targetKeys = ['new_lead'];
  }
  return targetKeys.map((key) => {
    const target = stageByKey(key);
    return { edgeId: `edge-${fromKey}-${key}`, toStatusId: target.id, label: `Move to ${target.label}` };
  });
}

function validateCustomFieldValue(
  def: { type: string; options: string[] | null },
  value: string | number | boolean,
): string | null {
  switch (def.type) {
    case 'number':
      return typeof value === 'number' && Number.isFinite(value) ? null : 'Enter a number.';
    case 'checkbox':
      return typeof value === 'boolean' ? null : 'Invalid value.';
    case 'email':
      return typeof value === 'string' && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)
        ? null
        : 'Enter a valid email address.';
    case 'url':
      try {
        void new URL(String(value));
        return null;
      } catch {
        return 'Enter a valid URL.';
      }
    case 'date':
      return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) ? null : 'Use YYYY-MM-DD.';
    case 'time':
      return typeof value === 'string' && /^\d{2}:\d{2}$/.test(value) ? null : 'Use HH:MM.';
    case 'list':
      return typeof value === 'string' && (def.options ?? []).includes(value)
        ? null
        : 'Choose one of the listed options.';
    default: // text
      return typeof value === 'string' && value.length <= 2000 ? null : 'Text is too long.';
  }
}

const TENANT = 'default';
const HOUR = 3_600_000;
const MIN = 60_000;

/** The signed-in agent the mock attributes outbound sends + self-claim to. */
export const MOCK_CURRENT_USER = { id: 'usr-demo', name: 'Demo User' };

const AGENT_NAMES: Record<string, string> = {
  'usr-demo': 'Demo User',
  'usr-amira': 'Amira Tan',
  'usr-jon': 'Jon Lim',
};

let idSeq = 1000;
const nextId = (prefix: string) => `${prefix}-${++idSeq}`;
const iso = (msAgo: number) => new Date(Date.now() - msAgo).toISOString();
const isoIn = (msAhead: number) => new Date(Date.now() + msAhead).toISOString();

// ---------------------------------------------------------------------------
// Seed data - one thread per UI state we need to tune (plan 05 Phase A).
// ---------------------------------------------------------------------------

type ThreadRow = ConversationThread;

/** Tag refs by name, resolved fresh from the contact-tag mock seed so the
 *  Tags tab and the thread chips agree on id/emoji/color at boot. */
function tagRef(name: string): ContactTagRef {
  const t = __mockAllContactTags('wsp-001').find((x) => x.name === name);
  if (!t) throw new Error(`Mock seed tag "${name}" not found`);
  return { id: t.id, name: t.name, emoji: t.emoji, color: t.color };
}

/** A WhatsApp thread's `windowExpiresAt` mirrors `cswExpiresAt` exactly
 *  (D-A7-5/R7) - the generalized window column reads the SAME instant, so
 *  deriving it here (rather than hand-duplicating every seed row) keeps the
 *  two provably in sync. */
type WhatsAppThreadSeed = Omit<ThreadRow, 'windowExpiresAt' | 'humanAgentExpiresAt'>;

function seedThreads(): ThreadRow[] {
  const whatsapp: WhatsAppThreadSeed[] = [
    {
      // Open CSW window, assigned to me - the happy free-form path. Plan 25:
      // Hot Lead stage, tagged VIP, 2 registered custom-field values.
      id: 'cnt-001', tenantId: TENANT, workspaceId: 'wsp-001',
      name: 'Sarah Chen', firstName: 'Sarah', lastName: 'Chen',
      phone: '+60 12-345 6789', email: 'sarah.chen@example.com',
      language: 'en', countryCode: 'MY', avatarUrl: null,
      assignedUserId: 'usr-demo', assignedUserName: 'Demo User',
      status: 'OPEN', priority: 'HIGH',
      channelId: 'chn-001', channelType: 'WHATSAPP',
      cswExpiresAt: isoIn(20 * HOUR), lastIncomingMessageAt: iso(4 * HOUR),
      lastMessageAt: iso(10 * MIN), lastMessagePreview: 'Can I change my booking to Saturday?',
      unreadCount: 2,
      customFields: { leadSource: 'Referral', company: 'Chen Events Sdn Bhd' },
      tags: [tagRef('VIP')],
      lifecycle: toLifecycleSummary(stageByKey('hot_lead')),
      createdAt: iso(72 * HOUR),
    },
    {
      // CSW EXPIRED - composer must lock, template-only. Payment stage.
      id: 'cnt-002', tenantId: TENANT, workspaceId: 'wsp-001',
      name: 'Marcus Wong', firstName: 'Marcus', lastName: 'Wong',
      phone: '+60 16-888 2211', email: 'marcus.wong@example.com',
      language: 'en', countryCode: 'MY', avatarUrl: null,
      assignedUserId: 'usr-demo', assignedUserName: 'Demo User',
      status: 'OPEN', priority: 'MEDIUM',
      channelId: 'chn-001', channelType: 'WHATSAPP',
      cswExpiresAt: iso(3 * HOUR), lastIncomingMessageAt: iso(27 * HOUR),
      lastMessageAt: iso(27 * HOUR), lastMessagePreview: 'Thanks, see you then!',
      unreadCount: 0,
      customFields: { leadSource: 'Website' },
      tags: [tagRef('Follow up')],
      lifecycle: toLifecycleSummary(stageByKey('payment')),
      createdAt: iso(9 * 24 * HOUR),
    },
    {
      // Unassigned bucket - self-claim path. Fresh New Lead, nothing set yet.
      id: 'cnt-003', tenantId: TENANT, workspaceId: 'wsp-001',
      name: 'Priya Raj', firstName: 'Priya', lastName: 'Raj',
      phone: '+60 17-202 0303', email: null,
      language: null, countryCode: null, avatarUrl: null,
      assignedUserId: null, assignedUserName: null,
      status: 'OPEN', priority: 'URGENT',
      channelId: 'chn-001', channelType: 'WHATSAPP',
      cswExpiresAt: isoIn(22 * HOUR), lastIncomingMessageAt: iso(30 * MIN),
      lastMessageAt: iso(30 * MIN), lastMessagePreview: 'Is the venue wheelchair accessible?',
      unreadCount: 1,
      customFields: {},
      tags: [],
      lifecycle: toLifecycleSummary(stageByKey('new_lead')),
      createdAt: iso(30 * MIN),
    },
    {
      // Assigned to a colleague - reassign path. All 3 tags (overflow "+N").
      id: 'cnt-004', tenantId: TENANT, workspaceId: 'wsp-001',
      name: 'Daniel Lee', firstName: 'Daniel', lastName: 'Lee',
      phone: '+60 11-555 7788', email: 'daniel.lee@example.com',
      language: 'en', countryCode: 'SG', avatarUrl: null,
      assignedUserId: 'usr-amira', assignedUserName: 'Amira Tan',
      status: 'SNOOZED', priority: 'LOW',
      channelId: 'chn-001', channelType: 'WHATSAPP',
      cswExpiresAt: isoIn(2 * HOUR), lastIncomingMessageAt: iso(22 * HOUR),
      lastMessageAt: iso(21 * HOUR), lastMessagePreview: 'No rush - next week is fine.',
      unreadCount: 0,
      customFields: {},
      tags: [tagRef('VIP'), tagRef('Follow up'), tagRef('Spam')],
      lifecycle: toLifecycleSummary(stageByKey('new_lead')),
      createdAt: iso(6 * 24 * HOUR),
    },
    {
      // Closed thread. Won (Customer) - terminal, no fireable moves.
      id: 'cnt-005', tenantId: TENANT, workspaceId: 'wsp-001',
      name: 'Aisha Abdullah', firstName: 'Aisha', lastName: 'Abdullah',
      phone: '+60 19-444 9090', email: 'aisha.abdullah@example.com',
      language: 'ms', countryCode: 'MY', avatarUrl: null,
      assignedUserId: 'usr-jon', assignedUserName: 'Jon Lim',
      status: 'CLOSED', priority: 'MEDIUM',
      channelId: 'chn-001', channelType: 'WHATSAPP',
      cswExpiresAt: iso(40 * HOUR), lastIncomingMessageAt: iso(64 * HOUR),
      lastMessageAt: iso(63 * HOUR), lastMessagePreview: 'Perfect, thank you so much!',
      unreadCount: 0,
      customFields: { dealValue: 15000, newsletterOptIn: true },
      tags: [],
      lifecycle: toLifecycleSummary(stageByKey('customer')),
      createdAt: iso(12 * 24 * HOUR),
    },
  ];
  return [
    ...whatsapp.map((t) => ({ ...t, windowExpiresAt: t.cswExpiresAt, humanAgentExpiresAt: null })),
    ...seedMetaThreads(),
  ];
}

/**
 * Plan 32 / A7a - Messenger + Instagram threads (AC-CHN-10): the three
 * composer window states (open / human-agent-extended / fully closed) plus
 * one Instagram thread, so the whole surface is exercisable with no backend.
 * `cswExpiresAt` stays null on every non-WhatsApp thread (D-A7-5, F4) - it is
 * a documented WhatsApp-only mirror. The app no longer binds to this module
 * at runtime (`conversation-service.ts` -> real, since plan 25) - these
 * seeds remain the standing frontend-first mock for future tuning + tests.
 */
function seedMetaThreads(): ThreadRow[] {
  return [
    {
      // Messenger, standard window OPEN - full composer capabilities.
      id: 'cnt-fb-001', tenantId: TENANT, workspaceId: 'wsp-001',
      name: 'Wei Ling Tan', firstName: 'Wei Ling', lastName: 'Tan',
      phone: null, email: null,
      language: null, countryCode: null, avatarUrl: null,
      assignedUserId: 'usr-demo', assignedUserName: 'Demo User',
      status: 'OPEN', priority: 'MEDIUM',
      channelId: 'chn-fb-001', channelType: 'FACEBOOK',
      cswExpiresAt: null, windowExpiresAt: isoIn(20 * HOUR), humanAgentExpiresAt: isoIn(164 * HOUR),
      lastIncomingMessageAt: iso(4 * HOUR),
      lastMessageAt: iso(4 * HOUR), lastMessagePreview: 'Do you deliver to Penang?',
      unreadCount: 1,
      customFields: {},
      tags: [],
      lifecycle: null,
      createdAt: iso(4 * HOUR),
    },
    {
      // Messenger, standard window CLOSED but human-agent window OPEN - the
      // composer stays enabled for a human agent (AC-CHN-08).
      id: 'cnt-fb-002', tenantId: TENANT, workspaceId: 'wsp-001',
      name: 'Aiman Farid', firstName: 'Aiman', lastName: 'Farid',
      phone: null, email: null,
      language: null, countryCode: null, avatarUrl: null,
      assignedUserId: 'usr-demo', assignedUserName: 'Demo User',
      status: 'OPEN', priority: 'LOW',
      channelId: 'chn-fb-001', channelType: 'FACEBOOK',
      cswExpiresAt: null, windowExpiresAt: iso(6 * HOUR), humanAgentExpiresAt: isoIn(138 * HOUR),
      lastIncomingMessageAt: iso(30 * HOUR),
      lastMessageAt: iso(30 * HOUR), lastMessagePreview: 'Thanks for the quote!',
      unreadCount: 0,
      customFields: {},
      tags: [],
      lifecycle: null,
      createdAt: iso(30 * HOUR),
    },
    {
      // Messenger, BOTH windows closed - composer locked, no template affordance.
      id: 'cnt-fb-003', tenantId: TENANT, workspaceId: 'wsp-001',
      name: 'Grace Lim', firstName: 'Grace', lastName: 'Lim',
      phone: null, email: null,
      language: null, countryCode: null, avatarUrl: null,
      assignedUserId: null, assignedUserName: null,
      status: 'OPEN', priority: 'LOW',
      channelId: 'chn-fb-001', channelType: 'FACEBOOK',
      cswExpiresAt: null, windowExpiresAt: iso(200 * HOUR), humanAgentExpiresAt: iso(32 * HOUR),
      lastIncomingMessageAt: iso(200 * HOUR),
      lastMessageAt: iso(200 * HOUR), lastMessagePreview: 'See you at the event.',
      unreadCount: 0,
      customFields: {},
      tags: [],
      lifecycle: null,
      createdAt: iso(200 * HOUR),
    },
    {
      // Instagram, standard window OPEN.
      id: 'cnt-ig-001', tenantId: TENANT, workspaceId: 'wsp-001',
      name: 'nur.aisyah', firstName: null, lastName: null,
      phone: null, email: null,
      language: null, countryCode: null, avatarUrl: null,
      assignedUserId: null, assignedUserName: null,
      status: 'OPEN', priority: 'MEDIUM',
      channelId: 'chn-ig-001', channelType: 'INSTAGRAM',
      cswExpiresAt: null, windowExpiresAt: isoIn(18 * HOUR), humanAgentExpiresAt: isoIn(162 * HOUR),
      lastIncomingMessageAt: iso(6 * HOUR),
      lastMessageAt: iso(6 * HOUR), lastMessagePreview: 'Love the new collection!',
      unreadCount: 1,
      customFields: {},
      tags: [],
      lifecycle: null,
      createdAt: iso(6 * HOUR),
    },
  ];
}

function seedMessages(): ConversationMessage[] {
  const msg = (
    contactId: string,
    senderType: ConversationMessage['senderType'],
    body: string,
    msAgo: number,
    extra: Partial<ConversationMessage> = {},
  ): ConversationMessage => ({
    id: nextId('msg'),
    contactId,
    channelId: 'chn-001',
    senderType,
    senderId: senderType === 'AGENT' ? 'usr-demo' : senderType === 'SYSTEM' ? 'usr-demo' : null,
    senderName: senderType === 'CONTACT' ? null : 'Demo User',
    messageType: 'TEXT',
    body,
    mediaUrl: null, mediaMime: null, mediaFilename: null, mediaSize: null, voice: false, payload: null,
    reactions: [],
    externalMessageId: senderType === 'CONTACT' ? nextId('wamid') : null,
    deliveryStatus: senderType === 'AGENT' ? 'READ' : null,
    errorCode: null,
    errorMessage: null,
    replyTo: null,
    createdAt: iso(msAgo),
    ...extra,
  });

  return [
    // cnt-001 - live thread: ticks in every state + an internal note.
    msg('cnt-001', 'CONTACT', 'Hi! I booked the Grand Ballroom for Friday.', 4 * HOUR + 40 * MIN),
    msg('cnt-001', 'AGENT', 'Hi Sarah! Yes, I can see your booking - Friday 7pm, 120 pax.', 4 * HOUR + 30 * MIN, { deliveryStatus: 'READ', externalMessageId: nextId('wamid') }),
    msg('cnt-001', 'SYSTEM', 'VIP client - handle with priority. Decision maker is Sarah.', 4 * HOUR + 25 * MIN),
    msg('cnt-001', 'CONTACT', 'Great. One more thing -', 4 * HOUR),
    msg('cnt-001', 'CONTACT', 'Can I change my booking to Saturday?', 10 * MIN),
    msg('cnt-001', 'AGENT', 'Checking availability now, give me a minute 🙏', 8 * MIN, { deliveryStatus: 'DELIVERED', externalMessageId: nextId('wamid') }),
    msg('cnt-001', 'AGENT', 'Saturday 7pm is free - shall I move it?', 6 * MIN, { deliveryStatus: 'SENT', externalMessageId: nextId('wamid') }),

    // cnt-002 - expired window + a FAILED outbound.
    msg('cnt-002', 'CONTACT', 'Confirming Friday 3pm site visit.', 28 * HOUR),
    msg('cnt-002', 'AGENT', 'Confirmed! See you at the lobby.', 27 * HOUR + 30 * MIN, { deliveryStatus: 'READ', externalMessageId: nextId('wamid') }),
    msg('cnt-002', 'CONTACT', 'Thanks, see you then!', 27 * HOUR),
    msg('cnt-002', 'AGENT', 'Quick update on parking…', 90 * MIN, {
      deliveryStatus: 'FAILED', externalMessageId: nextId('wamid'),
      errorCode: '131047', errorMessage: 'Re-engagement message - 24h window has passed.',
    }),

    // cnt-003 - single unanswered inbound (unassigned).
    msg('cnt-003', 'CONTACT', 'Is the venue wheelchair accessible?', 30 * MIN),

    // cnt-004 - snoozed thread.
    msg('cnt-004', 'CONTACT', 'Any update on the quotation?', 22 * HOUR),
    msg('cnt-004', 'AGENT', 'Finance is reviewing - I will revert by Thursday.', 21 * HOUR + 30 * MIN, { senderId: 'usr-amira', senderName: 'Amira Tan', deliveryStatus: 'READ', externalMessageId: nextId('wamid') }),
    msg('cnt-004', 'CONTACT', 'No rush - next week is fine.', 21 * HOUR),

    // cnt-005 - closed thread.
    msg('cnt-005', 'CONTACT', 'Received the invoice, paying today.', 64 * HOUR),
    msg('cnt-005', 'AGENT', 'Payment received - booking confirmed! 🎉', 63 * HOUR + 30 * MIN, { senderId: 'usr-jon', senderName: 'Jon Lim', deliveryStatus: 'READ', externalMessageId: nextId('wamid') }),
    msg('cnt-005', 'CONTACT', 'Perfect, thank you so much!', 63 * HOUR),
  ];
}

const TEMPLATES: WhatsAppTemplate[] = [
  {
    id: 'tpl-001', channelId: 'chn-001', name: 'booking_update', language: 'en',
    category: 'UTILITY', status: 'APPROVED',
    bodyText: 'Hi {{1}}, there is an update on your booking: {{2}}. Reply to this message to continue the conversation.',
    variableCount: 2, headerFormat: null, headerVariableCount: 0, buttonVariableCount: 0,
  },
  {
    id: 'tpl-002', channelId: 'chn-001', name: 'payment_reminder', language: 'en',
    category: 'UTILITY', status: 'APPROVED',
    bodyText: 'Hi {{1}}, a friendly reminder that invoice {{2}} is due on {{3}}.',
    variableCount: 3, headerFormat: null, headerVariableCount: 0, buttonVariableCount: 0,
  },
  {
    // TEXT header with a variable + a dynamic URL button (AC-12-22 rich send).
    id: 'tpl-004', channelId: 'chn-001', name: 'order_shipped', language: 'en',
    category: 'UTILITY', status: 'APPROVED',
    bodyText: 'Hi {{1}}, your order is on its way. Track it any time.',
    variableCount: 1, headerFormat: 'TEXT', headerVariableCount: 1, buttonVariableCount: 1,
  },
  {
    // Image header (media, uploaded-by-id at send).
    id: 'tpl-005', channelId: 'chn-001', name: 'new_venue_promo', language: 'en',
    category: 'MARKETING', status: 'APPROVED',
    bodyText: 'Big news {{1}}! Our new venue is now open.',
    variableCount: 1, headerFormat: 'IMAGE', headerVariableCount: 0, buttonVariableCount: 0,
  },
  {
    id: 'tpl-003', channelId: 'chn-001', name: 'promo_blast', language: 'en',
    category: 'MARKETING', status: 'PENDING', // not approved - must NOT be sendable
    bodyText: 'Big news {{1}}! Our new venue is open.',
    variableCount: 1, headerFormat: null, headerVariableCount: 0, buttonVariableCount: 0,
  },
];

const QUICK_REPLIES: QuickReply[] = [
  { id: 'qr-001', workspaceId: 'wsp-001', shortcut: '/hi', body: 'Hi! Thanks for reaching out to Foundryx Events - how can I help?' },
  { id: 'qr-002', workspaceId: 'wsp-001', shortcut: '/hours', body: 'Our office hours are Mon-Fri 9am-6pm (MYT).' },
  { id: 'qr-003', workspaceId: 'wsp-001', shortcut: '/payment', body: 'You can pay via bank transfer or card - the link is in your invoice email.' },
];

let threads: ThreadRow[] = seedThreads();
let messages: ConversationMessage[] = seedMessages();

// ---------------------------------------------------------------------------
// Emitter - fan-out to subscribers + the inbound/receipt simulator.
// ---------------------------------------------------------------------------

type Handler = (event: ConversationSocketEvent) => void;
// Phase A mock is single-workspace: one global room, the workspaceId param is
// accepted (interface parity) but not used for routing. The real Phase B WS
// scopes rooms per workspace.
const subscribers = new Set<Handler>();

function emit(_workspaceId: string, event: ConversationSocketEvent): void {
  subscribers.forEach((h) => h(event));
}

function threadOf(contactId: string): ThreadRow {
  const t = threads.find((x) => x.id === contactId);
  if (!t) throw new Error('Conversation not found');
  return t;
}

function touchThread(t: ThreadRow, patch: Partial<ThreadRow>): ThreadRow {
  const updated = { ...t, ...patch };
  threads = threads.map((x) => (x.id === t.id ? updated : x));
  return updated;
}

/**
 * Mirrors the backend's free-form send gate through the SAME generalized
 * window (plan 32 / A7a) the composer reads: WhatsApp keeps its exact
 * `cswExpiresAt` check; Messenger/Instagram allow a free-form send inside the
 * standard window OR the human-agent extension (the mock inbox always acts
 * as a human agent, D-A7-6) - the automation-only rejection is a backend/S2
 * concern, not modelled by this frontend mock.
 */
function mockWindowOpen(t: ThreadRow): boolean {
  const now = Date.now();
  if (t.channelType === 'WHATSAPP') {
    return !!t.cswExpiresAt && Date.parse(t.cswExpiresAt) > now;
  }
  const standardOpen = !!t.windowExpiresAt && Date.parse(t.windowExpiresAt) > now;
  const humanAgentOpen = !!t.humanAgentExpiresAt && Date.parse(t.humanAgentExpiresAt) > now;
  return standardOpen || humanAgentOpen;
}

/** Simulate Meta delivery receipts for an agent send: SENT→DELIVERED→READ. */
function simulateReceipts(message: ConversationMessage): void {
  const t = threads.find((x) => x.id === message.contactId);
  if (!t) return;
  const tick = (status: 'DELIVERED' | 'READ', after: number) =>
    setTimeout(() => {
      messages = messages.map((m) => (m.id === message.id ? { ...m, deliveryStatus: status } : m));
      emit(t.workspaceId, {
        type: 'message.status',
        messageId: message.id,
        contactId: message.contactId,
        deliveryStatus: status,
      });
    }, after);
  tick('DELIVERED', 1_500);
  tick('READ', 4_000);
}

const INBOUND_LINES = [
  'Sounds good 👍',
  'One more question - is outside catering allowed?',
  'Could you send me the floor plan?',
  'What time can vendors start setting up?',
];
let inboundSeq = 0;

/** Simulate a live inbound message on cnt-001 (the open thread). */
export function __mockSimulateInbound(workspaceId = 'wsp-001', contactId = 'cnt-001'): void {
  const t = threads.find((x) => x.id === contactId);
  if (!t) return;
  const body = INBOUND_LINES[inboundSeq++ % INBOUND_LINES.length];
  const message: ConversationMessage = {
    id: nextId('msg'), contactId, channelId: t.channelId,
    senderType: 'CONTACT', senderId: null, senderName: null,
    messageType: 'TEXT', body, mediaUrl: null, mediaMime: null, mediaFilename: null, mediaSize: null, voice: false, payload: null,
    reactions: [],
    externalMessageId: nextId('wamid'), deliveryStatus: null,
    errorCode: null, errorMessage: null, replyTo: null, createdAt: new Date().toISOString(),
  };
  messages = [...messages, message];
  const updated = touchThread(t, {
    status: 'OPEN', // inbound re-opens
    cswExpiresAt: isoIn(24 * HOUR),
    lastIncomingMessageAt: message.createdAt,
    lastMessageAt: message.createdAt,
    lastMessagePreview: body,
    unreadCount: t.unreadCount + 1,
  });
  emit(workspaceId, { type: 'message.created', message, thread: updated });
}

// ---------------------------------------------------------------------------
// Plan 27 - conversation events + shortcuts (S0 mock only; the events table +
// the `entity.shortcut` trigger land S1/S3). One seeded history per thread
// mixing status/assignment/lifecycle events so the Activities feed (merged
// with the SYSTEM notes above) has real variety to demo (AC-IVE-49).
// ---------------------------------------------------------------------------

let eventIdSeq = 1;
const nextEventId = () => `evt-${eventIdSeq++}`;

function ev(
  eventType: ConversationEvent['eventType'],
  msAgo: number,
  extra: Partial<ConversationEvent> = {},
): ConversationEvent {
  return {
    id: nextEventId(),
    eventType,
    actorName: MOCK_CURRENT_USER.name,
    actorUserId: MOCK_CURRENT_USER.id,
    fromValue: null,
    fromLabel: null,
    toValue: null,
    toLabel: null,
    closeReasonId: null,
    closeReasonName: null,
    note: null,
    payload: null,
    createdAt: iso(msAgo),
    ...extra,
  };
}

function seedEvents(): Record<string, ConversationEvent[]> {
  eventIdSeq = 1;
  const paymentReasonId =
    __mockAllCloseReasons('wsp-001').find((r) => r.name === 'Payment Issue')?.id ?? null;
  return {
    'cnt-001': [
      ev('opened', 72 * HOUR, { actorName: null, actorUserId: null }),
      ev('assigned', 71 * HOUR, { toValue: 'usr-demo', toLabel: 'Demo User', payload: { assigneeKind: 'user' } }),
      ev('first_agent_reply', 4 * HOUR + 30 * MIN, { payload: { responseSeconds: 600 } }),
    ],
    'cnt-002': [
      ev('opened', 9 * 24 * HOUR, { actorName: null, actorUserId: null }),
      ev('assigned', 9 * 24 * HOUR - MIN, { toValue: 'usr-demo', toLabel: 'Demo User', payload: { assigneeKind: 'user' } }),
    ],
    'cnt-003': [ev('opened', 30 * MIN, { actorName: null, actorUserId: null })],
    'cnt-004': [
      ev('opened', 6 * 24 * HOUR, { actorName: null, actorUserId: null }),
      ev('assigned', 6 * 24 * HOUR - MIN, {
        actorName: 'Amira Tan', actorUserId: 'usr-amira',
        toValue: 'usr-amira', toLabel: 'Amira Tan', payload: { assigneeKind: 'user' },
      }),
      ev('snoozed', 21 * HOUR, {
        actorName: 'Amira Tan', actorUserId: 'usr-amira', fromLabel: 'Open', toLabel: 'Snoozed',
      }),
    ],
    'cnt-005': [
      ev('opened', 12 * 24 * HOUR, { actorName: null, actorUserId: null }),
      ev('assigned', 12 * 24 * HOUR - MIN, {
        actorName: 'Jon Lim', actorUserId: 'usr-jon',
        toValue: 'usr-jon', toLabel: 'Jon Lim', payload: { assigneeKind: 'user' },
      }),
      ev('lifecycle_changed', 63 * HOUR + 45 * MIN, {
        actorName: 'Jon Lim', actorUserId: 'usr-jon', fromLabel: 'Payment', toLabel: 'Customer',
      }),
      ev('closed', 63 * HOUR, {
        actorName: 'Jon Lim', actorUserId: 'usr-jon',
        fromLabel: 'Open', toLabel: 'Closed',
        closeReasonId: paymentReasonId, closeReasonName: 'Payment Issue',
        note: 'Paid in full, booking confirmed.',
      }),
    ],
  };
}

let conversationEvents: Record<string, ConversationEvent[]> = seedEvents();

/** Three shortcut workflows (DoD - agent-browser smoke picks one to run). */
const SHORTCUT_WORKFLOWS: ShortcutItem[] = [
  { workflowId: 'wf-shortcut-nps', name: 'Send NPS survey' },
  { workflowId: 'wf-shortcut-escalate', name: 'Escalate to sales' },
  { workflowId: 'wf-shortcut-translate', name: 'Auto-translate and reply' },
];

let shortcutRunSeq = 1;

/** Reset mock state between tests. */
export function __mockResetConversations(): void {
  threads = seedThreads();
  messages = seedMessages();
  conversationEvents = seedEvents();
  shortcutRunSeq = 1;
  subscribers.clear();
  inboundSeq = 0;
}

// ---------------------------------------------------------------------------
// Service
// ---------------------------------------------------------------------------

function matches(t: ThreadRow, q: ThreadListQuery): boolean {
  // workspaceId intentionally NOT filtered: the mock is single-workspace but
  // the host page passes the REAL default-workspace uuid (workspace-service is
  // already live). Phase B's real impl scopes server-side.
  if (q.assignee === 'me' && t.assignedUserId !== MOCK_CURRENT_USER.id) return false;
  if (q.assignee === 'unassigned' && t.assignedUserId !== null) return false;
  if (q.status && q.status !== 'ALL' && t.status !== q.status) return false;
  if (q.priority && q.priority !== 'ALL' && t.priority !== q.priority) return false;
  if (q.search) {
    const s = q.search.toLowerCase();
    const hay = `${t.name} ${t.phone ?? ''} ${t.lastMessagePreview ?? ''}`.toLowerCase();
    if (!hay.includes(s)) return false;
  }
  return true;
}

/** Shared structured-send path (interactive/location/contacts) for the mock. */
function mockStructured(
  contactId: string,
  messageType: ConversationMessage['messageType'],
  payload: ConversationMessage['payload'],
  preview: string,
): Promise<ConversationMessage> {
  const t = threadOf(contactId);
  const windowOpen = mockWindowOpen(t);
  if (!windowOpen) {
    throw new Error('The 24-hour window has closed - send an approved template to re-engage.');
  }
  const message: ConversationMessage = {
    id: nextId('msg'), contactId, channelId: t.channelId,
    senderType: 'AGENT', senderId: MOCK_CURRENT_USER.id, senderName: MOCK_CURRENT_USER.name,
    messageType,
    body: messageType === 'INTERACTIVE' ? ((payload as { body?: string })?.body ?? null) : preview,
    mediaUrl: null, mediaMime: null, mediaFilename: null, mediaSize: null, voice: false,
    payload,
    reactions: [],
    externalMessageId: nextId('wamid'), deliveryStatus: 'SENT',
    errorCode: null, errorMessage: null, replyTo: null,
    createdAt: new Date().toISOString(),
  };
  messages = [...messages, message];
  const updated = touchThread(t, { lastMessageAt: message.createdAt, lastMessagePreview: preview });
  emit(t.workspaceId, { type: 'message.created', message, thread: updated });
  simulateReceipts(message);
  return delay(message, 250);
}

export const mockConversationService: ConversationService = {
  async listThreads(query) {
    const list = threads
      .filter((t) => matches(t, query))
      .sort((a, b) => (b.lastMessageAt ?? '').localeCompare(a.lastMessageAt ?? ''));
    return delay(list, 200);
  },

  async getThread(contactId) {
    return delay({ ...threadOf(contactId) }, 150);
  },

  async listMessages(contactId) {
    const t = threadOf(contactId);
    if (t.unreadCount > 0) touchThread(t, { unreadCount: 0 });
    const list = messages
      .filter((m) => m.contactId === contactId)
      .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
    return delay(list, 200);
  },

  async sendMessage(contactId, input: SendMessageInput) {
    const t = threadOf(contactId);
    const windowOpen = mockWindowOpen(t);

    let body: string;
    let messageType: ConversationMessage['messageType'];
    if (input.messageType === 'TEMPLATE') {
      const tpl = TEMPLATES.find((x) => x.id === input.templateId);
      if (!tpl) throw new Error('Template not found');
      if (tpl.status !== 'APPROVED') throw new Error('Template is not approved.');
      body = tpl.bodyText.replace(/\{\{(\d+)\}\}/g, (_, n) => input.templateVariables?.[Number(n) - 1] ?? '');
      messageType = 'TEMPLATE';
    } else {
      // Backend rule (plan 05 §5, decision 14): free-form only inside the CSW.
      if (!windowOpen) {
        throw new Error('The 24-hour window has closed - send an approved template to re-engage.');
      }
      if (!input.body?.trim()) throw new Error('Message body is required');
      body = input.body.trim();
      messageType = 'TEXT';
    }

    // Resolve the quoted message (WhatsApp Cloud `context.message_id` in Phase B).
    const quoted = input.replyToMessageId
      ? messages.find((m) => m.id === input.replyToMessageId && m.contactId === contactId)
      : undefined;

    const message: ConversationMessage = {
      id: nextId('msg'), contactId, channelId: t.channelId,
      senderType: 'AGENT', senderId: MOCK_CURRENT_USER.id, senderName: MOCK_CURRENT_USER.name,
      messageType, body, mediaUrl: null, mediaMime: null, mediaFilename: null, mediaSize: null, voice: false, payload: null,
      reactions: [],
      externalMessageId: nextId('wamid'), deliveryStatus: 'SENT',
      errorCode: null, errorMessage: null,
      replyTo: quoted
        ? { id: quoted.id, body: quoted.body, senderType: quoted.senderType, senderName: quoted.senderName }
        : null,
      createdAt: new Date().toISOString(),
    };
    messages = [...messages, message];
    const updated = touchThread(t, {
      lastMessageAt: message.createdAt,
      lastMessagePreview: body,
    });
    emit(t.workspaceId, { type: 'message.created', message, thread: updated });
    simulateReceipts(message);
    return delay(message, 250);
  },

  async sendTemplate(contactId, input: SendTemplateInput) {
    const tpl = TEMPLATES.find((x) => x.id === input.templateId);
    if (!tpl) throw new Error('Template not found');
    if (tpl.status !== 'APPROVED') throw new Error('Template is not approved.');
    // Mirror the backend count validation (AC-12-22).
    const headerVars = input.templateHeaderVariables ?? [];
    const bodyVars = input.templateVariables ?? [];
    const buttonVars = input.templateButtonVariables ?? [];
    if (tpl.headerFormat && tpl.headerFormat !== 'TEXT' && !input.headerFile) {
      throw new Error('This template has a media header - attach an image, video or document.');
    }
    if (headerVars.length !== tpl.headerVariableCount) {
      throw new Error(`This template's header needs ${tpl.headerVariableCount} variable(s); ${headerVars.length} provided.`);
    }
    if (bodyVars.length !== tpl.variableCount) {
      throw new Error(`This template's body needs ${tpl.variableCount} variable(s); ${bodyVars.length} provided.`);
    }
    if (buttonVars.length !== tpl.buttonVariableCount) {
      throw new Error(`This template's buttons need ${tpl.buttonVariableCount} variable(s); ${buttonVars.length} provided.`);
    }
    const t = threadOf(contactId);
    const body = tpl.bodyText.replace(/\{\{(\d+)\}\}/g, (_, n) => bodyVars[Number(n) - 1] ?? '');
    const message: ConversationMessage = {
      id: nextId('msg'), contactId, channelId: t.channelId,
      senderType: 'AGENT', senderId: MOCK_CURRENT_USER.id, senderName: MOCK_CURRENT_USER.name,
      messageType: 'TEMPLATE', body,
      mediaUrl: input.headerFile ? `/omnichannel/media/${nextId('media')}` : null,
      mediaMime: input.headerFile?.type ?? null,
      mediaFilename: input.headerFile?.name ?? null,
      mediaSize: input.headerFile?.size ?? null,
      voice: false, payload: null,
      reactions: [],
      externalMessageId: nextId('wamid'), deliveryStatus: 'SENT',
      errorCode: null, errorMessage: null, replyTo: null,
      createdAt: new Date().toISOString(),
    };
    messages = [...messages, message];
    const updated = touchThread(t, { lastMessageAt: message.createdAt, lastMessagePreview: body });
    emit(t.workspaceId, { type: 'message.created', message, thread: updated });
    simulateReceipts(message);
    return delay(message, 250);
  },

  async sendMedia(contactId, input: SendMediaInput) {
    const t = threadOf(contactId);
    const windowOpen = mockWindowOpen(t);
    if (!windowOpen) {
      throw new Error('The 24-hour window has closed - send an approved template to re-engage.');
    }
    const messageType = input.kind.toUpperCase() as ConversationMessage['messageType'];
    const message: ConversationMessage = {
      id: nextId('msg'), contactId, channelId: t.channelId,
      senderType: 'AGENT', senderId: MOCK_CURRENT_USER.id, senderName: MOCK_CURRENT_USER.name,
      messageType, body: input.caption ?? null,
      mediaUrl: `/omnichannel/media/${nextId('media')}`,
      mediaMime: input.file.type || null,
      mediaFilename: input.file.name,
      mediaSize: input.file.size,
      voice: input.kind === 'voice', payload: null,
      reactions: [],
      externalMessageId: nextId('wamid'), deliveryStatus: 'SENT',
      errorCode: null, errorMessage: null, replyTo: null,
      createdAt: new Date().toISOString(),
    };
    messages = [...messages, message];
    const updated = touchThread(t, {
      lastMessageAt: message.createdAt,
      lastMessagePreview: input.caption || `[${input.kind}]`,
    });
    emit(t.workspaceId, { type: 'message.created', message, thread: updated });
    simulateReceipts(message);
    return delay(message, 250);
  },

  async sendInteractive(contactId, input: SendInteractiveInput) {
    return mockStructured(contactId, 'INTERACTIVE', input.definition, input.definition.body);
  },
  async sendLocation(contactId, input: SendLocationInput) {
    const { replyToMessageId, ...loc } = input;
    void replyToMessageId;
    return mockStructured(contactId, 'LOCATION', loc, loc.name ?? loc.address ?? `${loc.lat}, ${loc.lng}`);
  },
  async sendContacts(contactId, input: SendContactsInput) {
    const name = input.contacts[0]?.name;
    const label = typeof name === 'string' ? name : (name?.formatted_name ?? 'Contact');
    return mockStructured(contactId, 'CONTACTS', { contacts: input.contacts }, label);
  },

  async react(contactId, messageId, emoji) {
    const clean = emoji.trim();
    const target = messages.find((m) => m.id === messageId);
    if (target) {
      const others = target.reactions.filter((r) => r.reactorType !== 'AGENT');
      const updated: ConversationMessage = {
        ...target,
        reactions: clean ? [...others, { emoji: clean, reactorType: 'AGENT', reactor: MOCK_CURRENT_USER.id }] : others,
      };
      messages = messages.map((m) => (m.id === messageId ? updated : m));
      const t = threadOf(contactId);
      emit(t.workspaceId, {
        type: 'message.reaction',
        targetMessageId: messageId,
        contactId,
        reactorType: 'AGENT',
        emoji: clean,
        removed: !clean,
      });
    }
    return delay({ targetMessageId: messageId, emoji: clean, removed: !clean }, 120);
  },

  async addInternalNote(contactId, body) {
    const t = threadOf(contactId);
    if (!body.trim()) throw new Error('Note body is required');
    const message: ConversationMessage = {
      id: nextId('msg'), contactId, channelId: t.channelId,
      senderType: 'SYSTEM', senderId: MOCK_CURRENT_USER.id, senderName: MOCK_CURRENT_USER.name,
      messageType: 'TEXT', body: body.trim(), mediaUrl: null, mediaMime: null, mediaFilename: null, mediaSize: null, voice: false, payload: null,
      reactions: [],
      externalMessageId: null, deliveryStatus: null,
      errorCode: null, errorMessage: null, replyTo: null, createdAt: new Date().toISOString(),
    };
    messages = [...messages, message];
    // AC-IVE-09/34 - a note also writes a `comment_added` event; the Activities
    // feed deliberately does NOT render this one as a separate line (the note
    // bubble already is the activity) - it exists so the event count/history
    // is honest if a future surface reads events without the note bodies.
    conversationEvents = {
      ...conversationEvents,
      [contactId]: [
        ...(conversationEvents[contactId] ?? []),
        ev('comment_added', 0, { payload: { messageId: message.id } }),
      ],
    };
    return delay(message, 150);
  },

  async assign(contactId, userId) {
    const t = threadOf(contactId);
    const updated = touchThread(t, {
      assignedUserId: userId,
      assignedUserName: userId ? (AGENT_NAMES[userId] ?? 'Agent') : null,
    });
    emit(t.workspaceId, { type: 'contact.updated', thread: updated });
    return delay({ ...updated }, 150);
  },

  async assignToMe(contactId) {
    return this.assign(contactId, MOCK_CURRENT_USER.id);
  },

  async setStatus(contactId, status: ThreadStatus) {
    const t = threadOf(contactId);
    const updated = touchThread(t, { status });
    emit(t.workspaceId, { type: 'contact.updated', thread: updated });
    return delay({ ...updated }, 150);
  },

  async setPriority(contactId, priority: ThreadPriority) {
    const t = threadOf(contactId);
    const updated = touchThread(t, { priority });
    emit(t.workspaceId, { type: 'contact.updated', thread: updated });
    return delay({ ...updated }, 150);
  },

  async listTemplates(channelId) {
    return delay(TEMPLATES.filter((x) => x.channelId === channelId && x.status === 'APPROVED'), 150);
  },

  // Single-workspace mock - the workspaceId param is unused (same reasoning as listThreads).
  async listQuickReplies() {
    return delay([...QUICK_REPLIES], 150);
  },

  async patchContact(contactId, patch: PatchContactInput) {
    const t = threadOf(contactId);
    const fieldErrors: Record<string, string> = {};

    if (patch.customFields) {
      const registry = __mockAllContactFields(t.workspaceId);
      for (const [key, value] of Object.entries(patch.customFields)) {
        if (value === null) continue; // explicit clear - always valid
        const def = registry.find((f) => f.key === key);
        if (!def) {
          fieldErrors[`customFields.${key}`] = 'This field is not registered for this workspace.';
          continue;
        }
        const err = validateCustomFieldValue(def, value);
        if (err) fieldErrors[`customFields.${key}`] = err;
      }
    }
    if (patch.email !== undefined && patch.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(patch.email)) {
      fieldErrors.email = 'Enter a valid email address.';
    }
    if (patch.language !== undefined && (patch.language?.length ?? 0) > 16) {
      fieldErrors.language = 'Language tag is too long.';
    }
    if (patch.countryCode !== undefined && patch.countryCode && !/^[A-Za-z]{2}$/.test(patch.countryCode)) {
      fieldErrors.countryCode = 'Use a 2-letter country code.';
    }
    let nextTags = t.tags;
    if (patch.tagIds) {
      const registry = __mockAllContactTags(t.workspaceId);
      const validIds = new Set(registry.map((tag) => tag.id));
      if (!patch.tagIds.every((id) => validIds.has(id))) {
        fieldErrors.tagIds = 'One or more tags do not belong to this workspace.';
      } else {
        nextTags = registry
          .filter((tag) => patch.tagIds!.includes(tag.id))
          .map((tag) => ({ id: tag.id, name: tag.name, emoji: tag.emoji, color: tag.color }));
      }
    }
    if (Object.keys(fieldErrors).length) {
      throw new ApiError('Please fix the highlighted fields.', 422, null, { fieldErrors });
    }

    const nextCustomFields = { ...t.customFields };
    if (patch.customFields) {
      for (const [key, value] of Object.entries(patch.customFields)) {
        if (value === null) delete nextCustomFields[key];
        else nextCustomFields[key] = value;
      }
    }
    const firstName = patch.firstName !== undefined ? patch.firstName : t.firstName;
    const lastName = patch.lastName !== undefined ? patch.lastName : t.lastName;
    const name = [firstName, lastName].filter(Boolean).join(' ').trim() || t.name;

    const updated = touchThread(t, {
      firstName,
      lastName,
      name,
      phone: patch.phone !== undefined ? patch.phone : t.phone,
      email: patch.email !== undefined ? patch.email : t.email,
      language: patch.language !== undefined ? patch.language : t.language,
      countryCode:
        patch.countryCode !== undefined
          ? (patch.countryCode ? patch.countryCode.toUpperCase() : patch.countryCode)
          : t.countryCode,
      customFields: nextCustomFields,
      tags: nextTags,
    });
    emit(t.workspaceId, { type: 'contact.updated', thread: updated });
    return delay({ ...updated }, 250);
  },

  async moveLifecycle(contactId, toStatusId) {
    const t = threadOf(contactId);
    if (!t.lifecycle) throw new Error('Lifecycle is not available for this contact.');
    const move = movesFrom(t.lifecycle.key).find((m) => m.toStatusId === toStatusId);
    const target = stageById(toStatusId);
    if (!move || !target) {
      throw new ApiError('No transition available to this stage.', 409, null, {
        code: 'lifecycle_move_not_allowed',
      });
    }
    const updated = touchThread(t, { lifecycle: toLifecycleSummary(target) });
    emit(t.workspaceId, { type: 'contact.updated', thread: updated });
    return delay({ ...updated }, 200);
  },

  async lifecycleMoves(contactId) {
    const t = threadOf(contactId);
    if (!t.lifecycle) return delay([], 150);
    return delay(movesFrom(t.lifecycle.key), 150);
  },

  subscribe(_workspaceId, handler) {
    subscribers.add(handler);
    return () => {
      subscribers.delete(handler);
    };
  },

  // -- Plan 27 additions (S0 mock; bound in conversation-service.ts) -----
  async closeThread(contactId, input: CloseThreadInput) {
    const t = threadOf(contactId);
    const reason = __mockAllCloseReasons(t.workspaceId).find((r) => r.id === input.closeReasonId);
    if (!reason || !reason.isActive) {
      throw new ApiError('Choose an active close reason.', 422, null, {
        fieldErrors: { closeReasonId: 'Choose an active close reason.' },
      });
    }
    if ((input.note?.length ?? 0) > 2000) {
      throw new ApiError('Note must be 2000 characters or fewer.', 422, null, {
        fieldErrors: { note: 'Note must be 2000 characters or fewer.' },
      });
    }
    const fromLabel = t.status === 'SNOOZED' ? 'Snoozed' : 'Open';
    const updated = touchThread(t, { status: 'CLOSED' });
    conversationEvents = {
      ...conversationEvents,
      [contactId]: [
        ...(conversationEvents[contactId] ?? []),
        ev('closed', 0, {
          fromLabel,
          toLabel: 'Closed',
          closeReasonId: reason.id,
          closeReasonName: reason.name,
          note: input.note?.trim() || null,
        }),
      ],
    };
    __mockBumpCloseReasonUse(reason.id);
    emit(t.workspaceId, { type: 'contact.updated', thread: updated });
    return delay({ ...updated }, 200);
  },

  async listEvents(contactId) {
    threadOf(contactId); // 404s (Error) if the contact doesn't exist / isn't ours
    const list = [...(conversationEvents[contactId] ?? [])].sort((a, b) =>
      b.createdAt.localeCompare(a.createdAt),
    );
    return delay(list, 150);
  },

  async listShortcuts(contactId) {
    threadOf(contactId);
    return delay([...SHORTCUT_WORKFLOWS], 150);
  },

  async runShortcut(contactId, workflowId) {
    threadOf(contactId);
    const workflow = SHORTCUT_WORKFLOWS.find((w) => w.workflowId === workflowId);
    if (!workflow) throw new ApiError('Shortcut workflow not found.', 404);
    return delay({ runId: `run-${shortcutRunSeq++}`, status: 'PENDING' }, 300);
  },
};
