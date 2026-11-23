/**
 * Fixed inbox data for the inbox tests (Foundryx UIUX slice W1-INBOX): a few
 * threads, lifecycle stages and saved views, all on a pinned clock.
 */
import type { ConversationThread, InboxView } from '@/types/omnichannel';
import type { StatusGraph } from '@/types/status-engine';

/** "Now" for every inbox test. */
export const INBOX_NOW = new Date('2026-06-05T08:00:00Z');

export function inboxThread(over: Partial<ConversationThread> = {}): ConversationThread {
  return {
    id: 'cnt-001',
    tenantId: 'ten-1',
    workspaceId: 'wsp-001',
    name: 'Aisyah binti Rahman',
    firstName: 'Aisyah',
    lastName: 'binti Rahman',
    phone: '+60123456789',
    email: null,
    language: null,
    countryCode: 'MY',
    avatarUrl: null,
    assignedUserId: 'usr-demo',
    assignedUserName: 'Nurul Huda',
    assignedTeamId: null,
    assignedTeamName: null,
    status: 'OPEN',
    priority: 'HIGH',
    channelId: 'chn-001',
    channelType: 'WHATSAPP',
    cswExpiresAt: '2026-06-06T07:00:00Z',
    windowExpiresAt: '2026-06-06T07:00:00Z',
    humanAgentExpiresAt: null,
    lastIncomingMessageAt: '2026-06-05T07:55:00Z',
    lastMessageAt: '2026-06-05T07:55:00Z',
    lastMessagePreview: 'Can I change the delivery date?',
    unreadCount: 2,
    customFields: {},
    tags: [
      { id: 'tag-1', name: 'VIP', emoji: null, color: null },
      { id: 'tag-2', name: 'Raya 2026', emoji: null, color: null },
      { id: 'tag-3', name: 'Florist', emoji: null, color: null },
    ],
    lifecycle: {
      statusId: 'stg-2',
      key: 'prospect',
      label: 'Prospect',
      color: '#3b82f6',
      isWon: false,
      isLost: false,
    },
    createdAt: '2026-01-02T03:04:05Z',
    ...over,
  };
}

export const INBOX_THREADS: ConversationThread[] = [
  inboxThread(),
  inboxThread({
    id: 'cnt-002',
    name: 'Lim Wei Jie',
    firstName: 'Wei Jie',
    lastName: 'Lim',
    assignedUserId: null,
    assignedUserName: null,
    status: 'SNOOZED',
    priority: 'MEDIUM',
    lastMessageAt: '2026-06-05T05:00:00Z',
    lastMessagePreview: 'Thanks, noted.',
    unreadCount: 0,
    tags: [],
    lifecycle: null,
  }),
  inboxThread({
    id: 'cnt-003',
    name: 'Kumar Ravi',
    firstName: 'Kumar',
    lastName: 'Ravi',
    status: 'CLOSED',
    priority: 'LOW',
    channelType: 'FACEBOOK',
    lastMessageAt: '2026-06-02T09:30:00Z',
    lastMessagePreview: 'See you next week',
    unreadCount: 0,
    tags: [{ id: 'tag-1', name: 'VIP', emoji: '⭐', color: null }],
  }),
];

export const INBOX_GRAPH: StatusGraph = {
  entityType: 'omnichannel_contact',
  source: 'tenant',
  statuses: [
    { id: 'stg-1', label: 'Lead', color: '#999999', sortOrder: 1 },
    { id: 'stg-2', label: 'Prospect', color: '#3b82f6', sortOrder: 2 },
    { id: 'stg-3', label: 'Customer', color: '#16a34a', sortOrder: 3 },
  ] as unknown as StatusGraph['statuses'],
  transitions: [],
};

export function inboxView(over: Partial<InboxView> = {}): InboxView {
  return {
    id: 'view-1',
    workspaceId: 'wsp-001',
    name: 'Raya orders',
    ownerUserId: 'usr-demo',
    ownerName: 'Demo User',
    isShared: false,
    filter: { statuses: ['OPEN'], sort: 'oldest' },
    sortOrder: 0,
    createdAt: '2026-01-01T00:00:00Z',
    ...over,
  };
}

export const INBOX_VIEWS: InboxView[] = [
  inboxView(),
  inboxView({ id: 'view-2', name: 'VIP follow-ups', isShared: true, ownerUserId: 'usr-kay', sortOrder: 1 }),
];

export const INBOX_TEAMS = [{ id: 'team-1', name: 'Sales team' }];
