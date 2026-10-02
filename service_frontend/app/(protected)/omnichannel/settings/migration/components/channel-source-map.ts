import type { ChannelType } from '@/types/omnichannel';

/**
 * Frontend mirror of the backend `SOURCE_TO_CHANNEL_TYPE` dict
 * (`modules/omnichannel/respondio/channel_map.py`, S1) - used ONLY to filter
 * the Channels-section picker to compatible targets (AC-MIG-04/31) before a
 * submit ever reaches the server, which re-derives the same mapping from
 * its own copy. `null` = no Foundryx `channelType` exists yet for that
 * respond.io source - forced "Skip this channel". Keep in sync with S1;
 * adding a channel type here needs no schema change (D-A6-10).
 */
export const SOURCE_TO_CHANNEL_TYPE: Record<string, ChannelType | null> = {
  whatsapp: 'WHATSAPP',
  whatsapp_cloud: 'WHATSAPP',
  '360dialog_whatsapp': 'WHATSAPP',
  twilio_whatsapp: 'WHATSAPP',
  message_bird_whatsapp: 'WHATSAPP',
  nexmo_whatsapp: 'WHATSAPP',
  facebook: 'FACEBOOK',
  instagram: 'INSTAGRAM',
  telegram: null,
  line: null,
  viber: null,
  wechat: null,
  twitter: null,
  custom_channel: null,
  gmail: null,
  other_email: null,
  twilio: null,
  message_bird: null,
  nexmo: null,
};
