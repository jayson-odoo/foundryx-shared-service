/**
 * Per-channel-type capabilities + messaging-window record (plan 32 / A7a §5.4,
 * §5.5). ONE exported record drives every UI gate that used to be a hardcoded
 * WhatsApp branch: the composer's attach menu, the CSW/window banner, the
 * channels list "Type" badge/icon and the thread-list/contacts-cell channel
 * icon lookups.
 *
 * Parity-pinned to the backend's authoritative `messaging_policy.CAPABILITIES`
 * / `messaging_policy.POLICIES` (`modules/omnichannel/services/
 * messaging_policy.py`) by the golden test in `channel-capabilities.test.ts`
 * (D-A7-10: a UX-only mirror, never a new wire field).
 *
 * What "parity-pinned" does and does not mean (review round 1, N9): the
 * backend record models `document`/`sticker`/`template`/`interactive_list`/
 * `location`/`contacts`/`reaction_outbound` and the window policy. It does
 * NOT model `image`/`video`/`audio`/`voice` at all - every implemented type
 * carries those - so those four flags are this file's own UX detail and the
 * golden test pins them here alone. The fields that DO exist on both sides
 * must agree exactly.
 */
import { CircleHelp, Facebook, Globe, Instagram, MessageCircle, type LucideIcon } from 'lucide-react';
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
  /** 'UNKNOWN' on the neutral fallback record (BL-SS-122) - never a modelled type. */
  channelType: ChannelType | 'UNKNOWN';
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
  // Plan 34 / A7b: parity-pinned against `messaging_policy.
  // CAPABILITIES["WEBCHAT"]` / `POLICIES["WEBCHAT"]` (§5.5). No external
  // provider on the far side (D-A7B-1), so there is no messaging window at
  // all - `reengageMode: 'none'` is the record every gate in this file
  // already understands (composer lock, window banner) via the existing
  // `reengageMode` checks, no new branch.
  WEBCHAT: {
    channelType: 'WEBCHAT',
    label: 'Web chat',
    icon: Globe,
    // Review round 1 (N5): the three Meta types echo a real external BRAND
    // hex, which is the only reason a raw colour is defensible in this file.
    // Web chat has no external provider (D-A7B-1) and therefore no brand to
    // echo, so its chip rides design tokens like every other non-brand
    // surface. The Meta hexes are deliberately left alone.
    accentClassName: 'bg-secondary text-secondary-foreground',
    windowHours: 0,
    humanAgentHours: null,
    reengageMode: 'none',
    // `voice` is TRUE (review round 1, N9): `messaging_policy.CAPABILITIES`
    // does not model the audio kinds at all and `webchat_projection.
    // _ALLOWED_MESSAGE_KINDS` includes `VOICE`, so a `false` here was a
    // silent divergence from the backend the header comment claims parity
    // with, not a deliberate restriction.
    media: { image: true, video: true, audio: true, voice: true, document: true, sticker: false },
    quickReplies: true,
    list: false,
    location: false,
    contacts: false,
    template: false,
    outboundReaction: false,
  },
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
export const CHANNEL_TYPES: ChannelType[] = ['WHATSAPP', 'FACEBOOK', 'INSTAGRAM', 'WEBCHAT'];

/**
 * Neutral fallback for a `channels.channel_type` value this build does not
 * model (BL-SS-122: no DB enum, so a legacy row or a backend-only type ahead
 * of its own frontend slice is a live possibility, not a theoretical one).
 * Generic icon, no brand accent, text-only capabilities, no messaging
 * window/re-engagement affordance - never crash the Channels/Contacts list,
 * thread list or drawer over an unmodelled type.
 */
const UNKNOWN_CAPABILITIES: ChannelCapabilities = {
  channelType: 'UNKNOWN',
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
 * types (a plain string on the wire, not a DB enum). The `(string & {})`
 * union member keeps `ChannelType` autocomplete at call sites while still
 * accepting an arbitrary wire string.
 */
export function channelCapabilities(channelType: ChannelType | (string & {})): ChannelCapabilities {
  return CHANNEL_CAPABILITIES[channelType as ChannelType] ?? UNKNOWN_CAPABILITIES;
}
