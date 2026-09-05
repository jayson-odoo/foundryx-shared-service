/**
 * Omnichannel BSP domain types (sprint-1 plan 04 - foundation).
 *
 * Mirrors the backend `app_omnichannel` schema the module will expose. Kept
 * framework-agnostic so the services + UI share one source. Phase A is mock-
 * backed; Phase B swaps the service implementations to the real api-client with
 * no change to these types. See documentation/plans/sprint-1/04-omnichannel-foundation.md.
 */

import type { UserStatus } from '@/types/user';

/** Channels the platform can connect. MVP builds WHATSAPP; others are later adapters. */
export type ChannelType = 'WHATSAPP' | 'FACEBOOK' | 'INSTAGRAM' | 'DOUYIN' | 'XIAOHONGSHU';

/** Connection lifecycle of a channel (maps to the static `statuses` table, CHANNEL scope). */
export type ChannelStatus = 'ACTIVE' | 'PENDING' | 'INACTIVE' | 'ERROR';

/** Lifecycle of a workspace (statuses table, WORKSPACE scope). */
export type WorkspaceStatus = 'ACTIVE' | 'INACTIVE';

/** A messaging workspace - a tenant-owned division channels/contacts/members hang off. */
export interface Workspace {
  id: string;
  tenantId: string;
  name: string;
  status: WorkspaceStatus;
  /** Denormalised counts surfaced in the list (server-computed in Phase B). */
  channelCount: number;
  memberCount: number;
  isDefault: boolean;
  isTrashed: boolean;
  createdAt: string; // ISO
  updatedAt: string; // ISO
}

/** A core user that is a member of a workspace (RBAC capability is separate). */
export interface WorkspaceMember {
  id: string; // membership row id
  userId: string;
  name: string | null;
  email: string;
  status: UserStatus;
  assignedAt: string; // ISO
}

/** A user eligible to be added as a workspace member (core users picker). */
export interface MemberCandidate {
  userId: string;
  name: string | null;
  email: string;
  status: UserStatus;
}

/** A connected channel (WhatsApp number, etc). Credentials never leave the backend. */
export interface Channel {
  id: string;
  tenantId: string;
  workspaceId: string;
  workspaceName: string;
  channelType: ChannelType;
  name: string;
  status: ChannelStatus;
  isActive: boolean;
  /** WhatsApp Business Account id (display only - read from Meta on connect). */
  wabaId: string | null;
  phoneNumberId: string | null;
  displayPhoneNumber: string | null;
  /** Meta business account name (synced read-only, plan 06). */
  businessAccountName: string | null;
  /** Meta verified display name (synced read-only, plan 06). */
  verifiedName: string | null;
  /** Last "Test Connection" / Sync outcome timestamp. */
  lastVerifiedAt: string | null;
  /** Last WhatsApp Business Profile sync timestamp. */
  profileSyncedAt: string | null;
  isTrashed: boolean;
  createdAt: string; // ISO
  updatedAt: string; // ISO
}

/** Mirrored WhatsApp Business Profile (plan 06 - Meta system-of-record). */
export interface ChannelProfile {
  about: string | null;
  address: string | null;
  description: string | null;
  email: string | null;
  vertical: string | null;
  website1: string | null;
  website2: string | null;
  /** Display-only current profile photo (upload deferred, BL-108). */
  profilePictureUrl: string | null;
  profileSyncedAt: string | null;
}

/** Editable + write-through profile fields (only changed fields POST to Meta). */
export interface UpdateChannelProfileInput {
  about?: string | null;
  address?: string | null;
  description?: string | null;
  email?: string | null;
  vertical?: string | null;
  website1?: string | null;
  website2?: string | null;
}

/** Editable fields on the channel detail form (most channel data is Meta-owned). */
export interface UpdateChannelInput {
  name?: string;
  isActive?: boolean;
}

/** Create/update a workspace. Members are managed separately (assign/remove). */
export interface CreateWorkspaceInput {
  name: string;
  status: WorkspaceStatus;
}
export interface UpdateWorkspaceInput {
  name?: string;
  status?: WorkspaceStatus;
}

/**
 * Result of the Meta Embedded Signup popup (the data the SDK hands back before
 * our backend exchanges the code). In Phase A the mock popup produces this; in
 * Phase B the real Meta JS SDK does. The backend turns `code` into a permanent
 * token + provisions the channel.
 */
export interface EmbeddedSignupResult {
  code: string;
  wabaId: string;
  phoneNumberId: string;
  /** Resolved server-side from phone_number_id when the real SDK omits them. */
  displayPhoneNumber?: string;
  businessName?: string;
  /** The origin the JS SDK dialog ran on - sent to the backend so the code
   *  exchange can pass a matching redirect_uri (required by Meta apps with
   *  "Use Strict Mode for redirect URIs" on). Absent for the simulated popup. */
  redirectUri?: string;
}

/** Manual channel connect - paste a System User token + phone ids (validation
 *  escape hatch before Business Verification). */
export interface ManualConnectInput {
  workspaceId: string;
  accessToken: string;
  phoneNumberId?: string;
  wabaId?: string;
  phoneNumber?: string;
}

/** A selectable WhatsApp number inside the (mock) Embedded Signup popup. */
export interface MockWabaOption {
  wabaId: string;
  businessName: string;
  phoneNumberId: string;
  displayPhoneNumber: string;
}

// ---------------------------------------------------------------------------
// Plan 05 - message processing (conversations, inbox, templates, quick replies)
// ---------------------------------------------------------------------------

/** Who authored a message bubble. SYSTEM = internal note (never sent to the contact). */
export type SenderType = 'AGENT' | 'CONTACT' | 'SYSTEM';

/** Message payload kinds (plan 12 - full media set; interactive/location/
 *  contacts/reaction land in slices 2/3). */
export type MessageType =
  | 'TEXT'
  | 'IMAGE'
  | 'VIDEO'
  | 'AUDIO'
  | 'VOICE'
  | 'DOCUMENT'
  | 'STICKER'
  | 'TEMPLATE'
  | 'INTERACTIVE'
  | 'INTERACTIVE_REPLY'
  | 'LOCATION'
  | 'CONTACTS'
  | 'REACTION';

/** The media-bearing kinds an agent can attach + send (plan 12 Slice 1). */
export type MediaKind = 'image' | 'video' | 'audio' | 'voice' | 'document' | 'sticker';

/** Outbound delivery lifecycle (Meta status webhooks drive transitions). QUEUED
 *  = the async send task hasn't reached Meta yet (optimistic bubble). */
export type DeliveryStatus = 'QUEUED' | 'SENT' | 'DELIVERED' | 'READ' | 'FAILED';

/** Thread lifecycle (statuses table, CONTACT scope). Inbound re-opens a thread. */
export type ThreadStatus = 'OPEN' | 'SNOOZED' | 'CLOSED';

/** Triage priority on a thread. */
export type ThreadPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'URGENT';

/**
 * A conversation thread = a contact + its thread metadata (mirrors backend
 * `contacts` - the contact IS the thread; messages hang off it).
 */
export interface ConversationThread {
  id: string; // contact id
  tenantId: string;
  workspaceId: string;
  /** Display name resolved from first/last name, else the raw profile name. */
  name: string;
  /** System fields (plan 25) - editable from the Contact panel Details tab. */
  firstName: string | null;
  lastName: string | null;
  phone: string | null;
  email: string | null;
  /** BCP-47 tag (e.g. "en", "zh-Hans"). */
  language: string | null;
  /** ISO-3166 alpha-2, upper-cased (e.g. "MY"). */
  countryCode: string | null;
  avatarUrl: string | null;
  assignedUserId: string | null;
  assignedUserName: string | null;
  status: ThreadStatus;
  priority: ThreadPriority;
  /** Channel the latest message arrived on (drives the thread-list icon). */
  channelId: string | null;
  channelType: ChannelType;
  /** 24h customer-service-window close time; null = never messaged in. */
  cswExpiresAt: string | null; // ISO
  lastIncomingMessageAt: string | null; // ISO
  lastMessageAt: string | null; // ISO
  /** Last visible message body (thread-list preview; server-computed). */
  lastMessagePreview: string | null;
  /** Inbound messages since the agent last opened the thread. */
  unreadCount: number;
  /** Registered custom-field values, keyed by `ContactField.key` (plan 25). */
  customFields: Record<string, string | number | boolean | null>;
  /** Tags attached to this contact (plan 25, AC-CDM-12). */
  tags: ContactTagRef[];
  /** Current lifecycle stage, or null before the module registers the entity
   *  (pre-migration / entity not yet adopted). */
  lifecycle: ContactLifecycleSummary | null;
  createdAt: string; // ISO
}

/** The quoted message a reply points at (WhatsApp `context.message_id`). */
export interface ReplyRef {
  id: string;
  body: string | null;
  senderType: SenderType;
  senderName: string | null;
}

/** One message bubble in a thread (mirrors backend `conversation_messages`). */
export interface ConversationMessage {
  id: string;
  contactId: string;
  channelId: string | null;
  senderType: SenderType;
  senderId: string | null;
  /** Resolved display name for AGENT/SYSTEM authors (server-joined). */
  senderName: string | null;
  messageType: MessageType;
  body: string | null;
  /** Relative blob-fetch path (`/omnichannel/media/{id}`) when media is stored;
   *  the bubble fetches it with the Bearer via `apiFetchBlob` (never `<img src>`). */
  mediaUrl: string | null;
  mediaMime: string | null;
  mediaFilename: string | null;
  mediaSize: number | null;
  /** True for a voice note (renders the voice-note player, not a plain audio). */
  voice: boolean;
  /** Structured payload for interactive / interactive-reply / location / contacts. */
  payload:
    | InteractiveDefinition
    | InteractiveReplyPayload
    | LocationPayload
    | ContactsPayload
    | null;
  /** Emoji reaction chips on this message (plan 12 Slice 3). */
  reactions: MessageReaction[];
  externalMessageId: string | null;
  deliveryStatus: DeliveryStatus | null;
  errorCode: string | null;
  errorMessage: string | null;
  /** Set when this message replies to another (stored in metadata_json). */
  replyTo: ReplyRef | null;
  createdAt: string; // ISO
}

/** One emoji reaction on a message (plan 12 Slice 3, AC-12-19/20). */
export interface MessageReaction {
  emoji: string;
  reactorType: 'CONTACT' | 'AGENT';
  reactor: string;
}

/** Header format of a template (drives which send input to show). */
export type TemplateHeaderFormat = 'TEXT' | 'IMAGE' | 'VIDEO' | 'DOCUMENT';

/** A synced (read-only) WhatsApp template - authoring lives in Meta (backlog). */
export interface WhatsAppTemplate {
  id: string;
  channelId: string;
  name: string;
  language: string | null;
  category: string | null;
  /** Approved body text with {{n}} placeholders (from components_json). */
  bodyText: string;
  /** Number of {{n}} variables the BODY expects. */
  variableCount: number;
  /** Header format, if the template has a header (plan 12 Slice 3). */
  headerFormat: TemplateHeaderFormat | null;
  /** Number of {{n}} variables a TEXT header expects (0 for media/none). */
  headerVariableCount: number;
  /** Number of dynamic URL buttons that need a value at send time. */
  buttonVariableCount: number;
  status: string | null; // APPROVED | PENDING | REJECTED (Meta-owned)
}

/** A canned response insertable from the composer (★ Quick Replies). */
export interface QuickReply {
  id: string;
  workspaceId: string;
  shortcut: string | null;
  body: string;
}

/** Compose payload. TEMPLATE requires templateId (+ variables); rest free-form. */
export interface SendMessageInput {
  messageType: 'TEXT' | 'TEMPLATE';
  body?: string;
  templateId?: string;
  templateVariables?: string[];
  /** Reply target (WhatsApp Cloud `context.message_id` in Phase B). */
  replyToMessageId?: string;
}

/** Outbound media send (plan 12 Slice 1). One file → one message; multi-select
 *  in the composer dispatches one of these per file. */
export interface SendMediaInput {
  kind: MediaKind;
  file: File;
  caption?: string;
  replyToMessageId?: string;
}

/** Send an approved template (plan 12 Slice 3, AC-12-22). Supplies BODY vars plus
 *  optional TEXT-header vars, dynamic URL-button vars, and a header-media file. */
export interface SendTemplateInput {
  templateId: string;
  /** BODY {{n}} values (positional). */
  templateVariables?: string[];
  /** TEXT-header {{n}} values (positional). */
  templateHeaderVariables?: string[];
  /** Dynamic URL-button values (in button order). */
  templateButtonVariables?: string[];
  /** Image/video/document header media (multipart when present). */
  headerFile?: File | null;
  replyToMessageId?: string;
}

// ---------------------------------------------------------------------------
// Plan 12 Slice 2 - interactive / location / contacts (structured payloads)
// ---------------------------------------------------------------------------

export type InteractiveKind = 'buttons' | 'list' | 'cta_url' | 'location_request';

export interface InteractiveButton {
  id: string;
  title: string;
}
export interface InteractiveListRow {
  id: string;
  title: string;
  description?: string;
}
export interface InteractiveListSection {
  title?: string;
  rows: InteractiveListRow[];
}
export interface InteractiveHeader {
  type: 'text' | 'image' | 'video' | 'document';
  text?: string;
}
/** The friendly interactive definition (stored in `payload_json`, rendered in the bubble). */
export interface InteractiveDefinition {
  kind: InteractiveKind;
  header?: InteractiveHeader | null;
  body: string;
  footer?: string | null;
  buttons?: InteractiveButton[];
  list?: { button: string; sections: InteractiveListSection[] };
  cta?: { displayText: string; url: string };
}

/** An inbound tapped reply (`INTERACTIVE_REPLY` payload). */
export interface InteractiveReplyPayload {
  kind: 'button' | 'list';
  id: string;
  title: string;
  description?: string | null;
}

export interface LocationPayload {
  lat: number;
  lng: number;
  name?: string | null;
  address?: string | null;
}

export interface ContactPhone {
  phone: string;
  type?: string;
  wa_id?: string;
}
export interface ContactCard {
  name: { formatted_name?: string; first_name?: string; last_name?: string } | string;
  phones: ContactPhone[];
}
export interface ContactsPayload {
  contacts: ContactCard[];
}

/** Send an interactive message (optional media header attached as a File). */
export interface SendInteractiveInput {
  definition: InteractiveDefinition;
  headerFile?: File | null;
  replyToMessageId?: string;
}
export interface SendLocationInput extends LocationPayload {
  replyToMessageId?: string;
}
export interface SendContactsInput {
  contacts: ContactCard[];
  replyToMessageId?: string;
}

/** Inbox thread-list filters (left panel - not the Resource shell). */
export interface ThreadListQuery {
  workspaceId?: string;
  assignee?: 'all' | 'me' | 'unassigned';
  status?: ThreadStatus | 'ALL';
  priority?: ThreadPriority | 'ALL';
  search?: string;
}

/** Realtime events fanned out per workspace (WS in Phase B; mock emitter in A). */
export type ConversationSocketEvent =
  | { type: 'message.created'; message: ConversationMessage; thread: ConversationThread }
  | { type: 'message.status'; messageId: string; contactId: string; deliveryStatus: DeliveryStatus; errorMessage?: string }
  | { type: 'contact.updated'; thread: ConversationThread }
  | {
      type: 'message.reaction';
      targetMessageId: string;
      contactId: string;
      reactorType: 'CONTACT' | 'AGENT';
      emoji: string;
      removed: boolean;
    };

/** Result of an agent reaction (POST …/react). */
export interface ReactionResult {
  targetMessageId: string;
  emoji: string;
  removed: boolean;
}

// ---------------------------------------------------------------------------
// Plan 25 - contact data model (typed fields, tags, lifecycle on the status
// engine). See documentation/plans/sprint-4/25-omnichannel-contact-data-model.md.
// ---------------------------------------------------------------------------

/** Custom contact-field value types (UAC Definitions - 8 total). */
export type ContactFieldType =
  | 'text'
  | 'list'
  | 'checkbox'
  | 'email'
  | 'number'
  | 'url'
  | 'date' // YYYY-MM-DD
  | 'time'; // HH:MM

/**
 * `always` = rendered inline in the Contact panel Details tab (AC-CDM-35);
 * `hidden` = registry-only (set via PATCH/workflow, never shown in the panel).
 */
export type ContactFieldVisibility = 'always' | 'hidden';

/** Reserved system-field keys (UAC Definitions) - never a registrable custom
 *  field key. Mirrors the backend reserved-key check (AC-CDM-02). */
export const RESERVED_CONTACT_FIELD_KEYS: readonly string[] = [
  'firstName',
  'lastName',
  'phone',
  'email',
  'language',
  'countryCode',
  'tags',
  'lifecycle',
  'profilePic',
];

/** A registered custom field (per workspace). Values live in
 *  `ConversationThread.customFields[key]`. */
export interface ContactField {
  id: string;
  workspaceId: string;
  key: string;
  label: string;
  description: string | null;
  type: ContactFieldType;
  /** `list` type only - the selectable option strings. */
  options: string[] | null;
  visibility: ContactFieldVisibility;
  sortOrder: number;
  /** Contacts currently holding a non-null value for this field (delete
   *  confirmation copy, AC-CDM-31). */
  valuesCount: number;
  createdAt: string; // ISO
}

export interface CreateContactFieldInput {
  key: string;
  label: string;
  description?: string | null;
  type: ContactFieldType;
  /** Required (>= 1) when `type === 'list'`. */
  options?: string[];
  visibility?: ContactFieldVisibility;
}

/** `key` and `type` are immutable after create (D6) - omit both from updates. */
export interface UpdateContactFieldInput {
  label?: string;
  description?: string | null;
  options?: string[];
  visibility?: ContactFieldVisibility;
  sortOrder?: number;
}

/** A tag (per workspace), attached to contacts via a replace-set PATCH. */
export interface ContactTag {
  id: string;
  workspaceId: string;
  name: string;
  emoji: string | null;
  color: string | null; // hex
  description: string | null;
  contactsCount: number;
  createdAt: string; // ISO
}

export interface CreateContactTagInput {
  name: string;
  emoji?: string | null;
  color?: string | null;
  description?: string | null;
}

export interface UpdateContactTagInput {
  name?: string;
  emoji?: string | null;
  color?: string | null;
  description?: string | null;
}

/** Compact tag ref carried on a thread/message item (AC-CDM-12). */
export interface ContactTagRef {
  id: string;
  name: string;
  emoji: string | null;
  color: string | null;
}

/** The contact's current lifecycle stage, as carried on a `ThreadItem`
 *  (AC-CDM-19) - `isWon` mirrors the status engine's `is_terminal`, `isLost`
 *  mirrors `is_archived`. */
export interface ContactLifecycleSummary {
  statusId: string;
  key: string;
  label: string;
  color: string | null;
  isWon: boolean;
  isLost: boolean;
}

/** One fireable outgoing edge from the contact's current stage (AC-CDM-18) -
 *  the ONLY moves the "Move to" picker may offer (foolproof-UI). */
export interface LifecycleMove {
  edgeId: string;
  toStatusId: string;
  label: string;
}

/**
 * Partial-merge contact PATCH (system fields + typed custom fields + tag
 * replace-set). `customFields` value `null` clears that key; keys omitted from
 * `customFields` are left unchanged (partial merge, NOT replace). `tagIds`
 * REPLACES the contact's whole tag set (AC-CDM-06/07/10).
 */
export interface PatchContactInput {
  firstName?: string | null;
  lastName?: string | null;
  phone?: string | null;
  email?: string | null;
  language?: string | null;
  countryCode?: string | null;
  customFields?: Record<string, string | number | boolean | null>;
  tagIds?: string[];
}
