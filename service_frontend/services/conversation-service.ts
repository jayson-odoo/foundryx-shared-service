/**
 * Conversation service — boundary the inbox UI talks to (plan 05).
 *
 * Phase A binds the MOCK (threads, messages, a timer-driven emitter that
 * simulates inbound messages + delivery receipts). Phase B swaps
 * `conversationService` to the real api-client + WebSocket impl in ONE line
 * (bottom), exactly like channel-service did.
 */
import type {
  ConversationMessage,
  ConversationSocketEvent,
  ConversationThread,
  QuickReply,
  SendContactsInput,
  SendInteractiveInput,
  SendLocationInput,
  SendMediaInput,
  SendMessageInput,
  ThreadListQuery,
  ThreadPriority,
  ThreadStatus,
  WhatsAppTemplate,
} from '@/types/omnichannel';
import { realConversationService } from './conversation-service.real';

export interface ConversationService {
  /** Thread list for the inbox left panel, sorted by lastMessageAt desc. */
  listThreads(query: ThreadListQuery): Promise<ConversationThread[]>;
  getThread(contactId: string): Promise<ConversationThread>;
  /** Full message history for a thread (oldest → newest). Marks thread read. */
  listMessages(contactId: string): Promise<ConversationMessage[]>;
  /** Send free-form/template. Backend enforces CSW; mock mirrors the rule. */
  sendMessage(contactId: string, input: SendMessageInput): Promise<ConversationMessage>;
  /** Send a media file (image/video/audio/voice/document/sticker) — multipart.
   *  Backend sniff-gates + cap-checks then queues the async upload-by-id send. */
  sendMedia(contactId: string, input: SendMediaInput): Promise<ConversationMessage>;
  /** Send an interactive message (reply-buttons/list/CTA-URL/location-request). */
  sendInteractive(contactId: string, input: SendInteractiveInput): Promise<ConversationMessage>;
  /** Send a location (coords + optional name/address). */
  sendLocation(contactId: string, input: SendLocationInput): Promise<ConversationMessage>;
  /** Send one or more contact cards. */
  sendContacts(contactId: string, input: SendContactsInput): Promise<ConversationMessage>;
  /** Internal note (SYSTEM bubble) — never delivered to the contact. */
  addInternalNote(contactId: string, body: string): Promise<ConversationMessage>;
  /** Assign/reassign (userId) or unassign (null). */
  assign(contactId: string, userId: string | null): Promise<ConversationThread>;
  /** Self-claim — assignee = the authenticated actor (server-resolved in Phase B). */
  assignToMe(contactId: string): Promise<ConversationThread>;
  /** Open / snooze / close lifecycle. */
  setStatus(contactId: string, status: ThreadStatus): Promise<ConversationThread>;
  setPriority(contactId: string, priority: ThreadPriority): Promise<ConversationThread>;
  /** Approved templates for the thread's channel (CSW-locked composer picker). */
  listTemplates(channelId: string): Promise<WhatsAppTemplate[]>;
  /** Canned responses for the workspace (★ composer picker). */
  listQuickReplies(workspaceId: string): Promise<QuickReply[]>;
  /**
   * Subscribe to realtime events for a workspace. Returns an unsubscribe fn.
   * Phase B: WebSocket + Redis pub/sub; Phase A: mock timer emitter.
   */
  subscribe(workspaceId: string, handler: (event: ConversationSocketEvent) => void): () => void;
}

// Phase B: real api-client + WS implementation. (Mock retained in *.mock.ts.)
export const conversationService: ConversationService = realConversationService;
