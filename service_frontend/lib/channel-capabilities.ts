/**
 * Per-channel-type capabilities + messaging-window record (plan 32 / A7a §5.4,
 * §5.5). ONE exported record drives every UI gate that used to be a hardcoded
 * WhatsApp branch: the composer's attach menu, the CSW/window banner, the
 * channels list "Type" badge/icon and the thread-list/contacts-cell channel
 * icon lookups.
 *
 * Parity-pinned to the backend's authoritative `messaging_policy.CAPABILITIES`
 * / `messaging_policy.POLICIES` (`modules/omnichannel/services/
 * messaging_policy.py`, landing in S2) by a golden test once that module
 * exists - `channel-capabilities.test.ts` pins this side of the contract now
 * (D-A7-10: a UX-only mirror, never a new wire field).
 */
import { CircleHelp, Facebook, Instagram, MessageCircle, type LucideIcon } from 'lucide-react';
import type { ChannelType } from '@/types/omnichannel';

/** How a channel type re-engages a contact once its standard window closes. */
export type ReengageMode = 'template' | 'human_agent' | 'none';

/** The message kinds a channel type can carry (composer gating; server-
 *  enforced in `messaging_policy.assert_kind_supported` - the frontend read of
 *  this record is UX only, D-A7-29). */
export interface ChannelMediaCapabilities {
  image: boolean;
  video: boolean;
  audio: boolean;
  /** Voice notes ride the `audio` message kind on Messenger/Instagram. */
  voice: boolean;
  document: boolean;
  sticker: boolean;
}

export interface ChannelCapabilities {
  channelType: ChannelType;
  label: string;
  icon: LucideIcon;
  /** Brand-ish accent used for the small channel-type icon chip. */
  accentClassName: string;
  /** Standard messaging window, in hours (24h for every implemented type today). */
  windowHours: number;
  /** Extended human-agent window, in hours; null = no extension (WhatsApp). */
  humanAgentHours: number | null;
  reengageMode: ReengageMode;
  media: ChannelMediaCapabilities;
  /** Structured interactive buttons - sent as Meta quick replies on Messenger/
   *  Instagram (D-A7-13), as WhatsApp interactive buttons on WhatsApp. */
  quickReplies: boolean;
  /** WhatsApp-only interactive LIST message. */
  list: boolean;
  /** WhatsApp-only location message. */
  location: boolean;
  /** WhatsApp-only contacts-card message. */
  contacts: boolean;
  /** Approved message templates (re-engagement outside the standard window). */
  template: boolean;
  /** Outbound reactions (inbound reactions land on the existing path for
   *  every type regardless of this flag). */
  outboundReaction: boolean;
}

export const CHANNEL_CAPABILITIES: Record<ChannelType, ChannelCapabilities> = {
  WHATSAPP: {
    channelType: 'WHATSAPP',
    label: 'WhatsApp',
    icon: MessageCircle,
    accentClassName: 'bg-[#25D366]/10 text-[#25D366]',
    windowHours: 24,
    humanAgentHours: null,
    reengageMode: 'template',
    media: { image: true, video: true, audio: true, voice: true, document: true, sticker: true },
    quickReplies: true,
    list: true,
    location: true,
    contacts: true,
    template: true,
    outboundReaction: true,
  },
  FACEBOOK: {
    channelType: 'FACEBOOK',
    label: 'Messenger',
    icon: Facebook,
    accentClassName: 'bg-[#1877F2]/10 text-[#1877F2]',
    windowHours: 24,
    humanAgentHours: 168,
    reengageMode: 'human_agent',
    media: { image: true, video: true, audio: true, voice: true, document: true, sticker: false },
    quickReplies: true,
    list: false,
    location: false,
    contacts: false,
    template: false,
    outboundReaction: false,
  },
  INSTAGRAM: {
    channelType: 'INSTAGRAM',
    label: 'Instagram',
    icon: Instagram,
    accentClassName: 'bg-[#E1306C]/10 text-[#E1306C]',
    windowHours: 24,
    humanAgentHours: 168,
    reengageMode: 'human_agent',
    // Instagram declares its own row independently of Messenger (D-A7-9/R9) -
    // a future Meta policy divergence is a one-row change. Today it differs
    // only in `document` (no file attachments on Instagram, capability table
    // §5.5).
    media: { image: true, video: true, audio: true, voice: true, document: false, sticker: false },
    quickReplies: true,
    list: false,
    location: false,
    contacts: false,
    template: false,
    outboundReaction: false,
  },
};

/** Ordered list for pickers (connect wizard channel-type step, filters). */
export const CHANNEL_TYPES: ChannelType[] = ['WHATSAPP', 'FACEBOOK', 'INSTAGRAM'];

/**
 * Neutral fallback for a `channels.channel_type` value this build does not
 * model (BL-SS-122: no DB enum, so a legacy row or a backend-only type ahead
 * of its own frontend slice is a live possibility, not a theoretical one).
 * Generic icon, no brand accent, text-only capabilities, no messaging
 * window/re-engagement affordance - never crash the Channels/Contacts list,
 * thread list or drawer over an unmodelled type.
 */
const UNKNOWN_CAPABILITIES: ChannelCapabilities = {
  // `channelType` is unread on this record (every call site already has the
  // raw string it looked up) - 'WHATSAPP' is a type-shape placeholder only.
  channelType: 'WHATSAPP',
  label: 'Unknown',
  icon: CircleHelp,
  accentClassName: 'bg-mono/10 text-mono',
  windowHours: 0,
  humanAgentHours: null,
  reengageMode: 'none',
  media: { image: false, video: false, audio: false, voice: false, document: false, sticker: false },
  quickReplies: false,
  list: false,
  location: false,
  contacts: false,
  template: false,
  outboundReaction: false,
};

/**
 * The one lookup every call site must go through instead of indexing
 * `CHANNEL_CAPABILITIES` directly - falls back to `UNKNOWN_CAPABILITIES`
 * rather than throwing when `channelType` is not one of the three modelled
 * types (a plain string on the wire, not a DB enum).
 */
export function channelCapabilities(channelType: string): ChannelCapabilities {
  return CHANNEL_CAPABILITIES[channelType as ChannelType] ?? UNKNOWN_CAPABILITIES;
}
