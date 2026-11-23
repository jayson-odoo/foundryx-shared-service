/**
 * Shared data for the contact record tests (parity and the Foundryx UIUX
 * tests). Data only: every test file declares its own module mocks.
 */
import type {
  ContactField,
  ContactListItem,
  ContactTag,
  ConversationThread,
} from '@/types/omnichannel';
import { encodeListQuery } from '@/lib/list-context';
import type { LifecycleStageOption } from '@/hooks/use-contact-lifecycle-stages';

export const RECORD_ID = 'cnt-001';

export function recordThread(
  over: Partial<ConversationThread> = {},
): ConversationThread {
  return {
    id: RECORD_ID,
    tenantId: 'ten-1',
    workspaceId: 'wsp-1',
    name: 'Aisyah binti Rahman',
    firstName: 'Aisyah',
    lastName: 'binti Rahman',
    phone: '+60123456789',
    email: 'aisyah@example.com',
    language: 'ms',
    countryCode: 'MY',
    avatarUrl: null,
    assignedUserId: null,
    assignedUserName: null,
    status: 'OPEN',
    priority: 'MEDIUM',
    channelId: 'chn-demo',
    channelType: 'WHATSAPP',
    cswExpiresAt: null,
    windowExpiresAt: null,
    humanAgentExpiresAt: null,
    lastIncomingMessageAt: null,
    lastMessageAt: null,
    lastMessagePreview: null,
    unreadCount: 0,
    customFields: { company: 'Kedai Bunga Mawar', vip: true },
    tags: [{ id: 'tag-1', name: 'VIP', emoji: null, color: '#FF5A00' }],
    lifecycle: {
      statusId: 'st-customer',
      key: 'customer',
      label: 'Customer',
      color: '#16a34a',
      isWon: false,
      isLost: false,
    },
    createdAt: '2026-01-01T00:00:00Z',
    ...over,
  } as ConversationThread;
}

export function recordItem(
  over: Partial<ContactListItem> = {},
): ContactListItem {
  return {
    ...recordThread(),
    channels: [],
    messageCount: 12,
    fileCount: 2,
    ...over,
  } as ContactListItem;
}

export const FIELDS: ContactField[] = [
  {
    id: 'cf-1',
    workspaceId: 'wsp-1',
    key: 'company',
    label: 'Company',
    description: null,
    type: 'text',
    options: null,
    visibility: 'always',
    sortOrder: 0,
    valuesCount: 1,
    createdAt: '2026-01-01T00:00:00Z',
  },
  {
    id: 'cf-2',
    workspaceId: 'wsp-1',
    key: 'vip',
    label: 'VIP member',
    description: null,
    type: 'checkbox',
    options: null,
    visibility: 'always',
    sortOrder: 1,
    valuesCount: 1,
    createdAt: '2026-01-01T00:00:00Z',
  },
] as ContactField[];

export const TAGS: ContactTag[] = [
  {
    id: 'tag-1',
    workspaceId: 'wsp-1',
    name: 'VIP',
    emoji: null,
    color: '#FF5A00',
    description: null,
    contactsCount: 1,
    createdAt: '2026-01-01T00:00:00Z',
  },
  {
    id: 'tag-2',
    workspaceId: 'wsp-1',
    name: 'Florist',
    emoji: null,
    color: null,
    description: null,
    contactsCount: 0,
    createdAt: '2026-01-01T00:00:00Z',
  },
] as ContactTag[];

export const STAGES: LifecycleStageOption[] = [
  {
    id: 'st-lead',
    key: 'lead',
    label: 'Lead',
    color: '#64748b',
    isInitial: true,
    isTerminal: false,
    isArchived: false,
  },
  {
    id: 'st-customer',
    key: 'customer',
    label: 'Customer',
    color: '#16a34a',
    isInitial: false,
    isTerminal: false,
    isArchived: false,
  },
];

export const MOVES = [{ toStatusId: 'st-lead', label: 'Lead' }];

/** A list context carried from the contacts list (record 3 of 137). */
export const LIST_CTX = encodeListQuery({ page: 1, pageSize: 50, search: '' });
