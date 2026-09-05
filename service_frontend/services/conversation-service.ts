/**
 * Conversation service - boundary the inbox UI talks to (plan 05).
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
  LifecycleMove,
  PatchContactInput,
  QuickReply,
  ReactionResult,
  SendContactsInput,
  SendInteractiveInput,
  SendLocationInput,
  SendMediaInput,
  SendMessageInput,
  SendTemplateInput,
  ThreadListQuery,
  ThreadPriority,
  ThreadStatus,
  WhatsAppTemplate,
} from '@/types/omnichannel';
import { mockConversationService } from './conversation-service.mock';

export interface ConversationService {
  /** Thread list for the inbox left panel, sorted by lastMessageAt desc. */
  listThreads(query: ThreadListQuery): Promise<ConversationThread[]>;
  getThread(contactId: string): Promise<ConversationThread>;
  /** Full message history for a thread (oldest → newest). Marks thread read. */
  listMessages(contactId: string): Promise<ConversationMessage[]>;
  /** Send free-form/template. Backend enforces CSW; mock mirrors the rule. */
  sendMessage(contactId: string, input: SendMessageInput): Promise<ConversationMessage>;
  /** Send an approved template (BODY + TEXT-header + URL-button vars + optional
   *  header media). Multipart when a header file is attached (AC-12-22). */
  sendTemplate(contactId: string, input: SendTemplateInput): Promise<ConversationMessage>;
  /** Send a media file (image/video/audio/voice/document/sticker) - multipart.
   *  Backend sniff-gates + cap-checks then queues the async upload-by-id send. */
  sendMedia(contactId: string, input: SendMediaInput): Promise<ConversationMessage>;
  /** Send an interactive message (reply-buttons/list/CTA-URL/location-request). */
  sendInteractive(contactId: string, input: SendInteractiveInput): Promise<ConversationMessage>;
  /** Send a location (coords + optional name/address). */
  sendLocation(contactId: string, input: SendLocationInput): Promise<ConversationMessage>;
  /** Send one or more contact cards. */
  sendContacts(contactId: string, input: SendContactsInput): Promise<ConversationMessage>;
  /** React to a message by its durable id (empty emoji removes). */
  react(contactId: string, messageId: string, emoji: string): Promise<ReactionResult>;
  /** Internal note (SYSTEM bubble) - never delivered to the contact. */
  addInternalNote(contactId: string, body: string): Promise<ConversationMessage>;
  /** Assign/reassign (userId) or unassign (null). */
  assign(contactId: string, userId: string | null): Promise<ConversationThread>;
  /** Self-claim - assignee = the authenticated actor (server-resolved in Phase B). */
  assignToMe(contactId: string): Promise<ConversationThread>;
  /** Open / snooze / close lifecycle. */
  setStatus(contactId: string, status: ThreadStatus): Promise<ConversationThread>;
  setPriority(contactId: string, priority: ThreadPriority): Promise<ConversationThread>;
  /** Approved templates for the thread's channel (CSW-locked composer picker). */
  listTemplates(channelId: string): Promise<WhatsAppTemplate[]>;
  /** Canned responses for the workspace (★ composer picker). */
  listQuickReplies(workspaceId: string): Promise<QuickReply[]>;
  /**
   * Plan 25 - system fields + typed custom fields + tag replace-set, ONE
   * partial-merge PATCH (AC-CDM-06/07/10, AC-CDM-36). 422 `fieldErrors` map
   * onto `customFields.<key>` / `tagIds` / `language` / `countryCode` / etc.
   */
  patchContact(contactId: string, patch: PatchContactInput): Promise<ConversationThread>;
  /** Move the contact's lifecycle stage via the status-engine machine
   *  (AC-CDM-17). 409 when no edge exists from the current stage. */
  moveLifecycle(contactId: string, toStatusId: string): Promise<ConversationThread>;
  /** The fireable outgoing edges from the contact's CURRENT stage only - the
   *  "Move to" picker offers ONLY these (AC-CDM-18, foolproof-UI). */
  lifecycleMoves(contactId: string): Promise<LifecycleMove[]>;
  /**
   * Subscribe to realtime events for a workspace. Returns an unsubscribe fn.
   * Phase B: WebSocket + Redis pub/sub; Phase A: mock timer emitter.
   */
  subscribe(workspaceId: string, handler: (event: ConversationSocketEvent) => void): () => void;
}

// S0 MOCK - swap to real in S4 (plan 25). The rest of the omnichannel message
// pipeline (plan 05) already shipped against `realConversationService`
// (conversation-service.real.ts); this slice temporarily rebinds to the mock
// so the NEW contact-panel surfaces (lifecycle move, tag add/remove, typed
// custom fields) are fully tunable with no backend - the lifecycle/tags/
// customFields routes don't exist until S1-S3. `realConversationService` is
// fully implemented (incl. the 3 new methods) and swaps back in with this one
// line once the backend lands.
export const conversationService: ConversationService = mockConversationService;
