import type { StatusRegistry } from '@/components/platform/status-badge';
import type { ChannelStatus, ChannelType } from '@/types/omnichannel';
import { CHANNEL_CAPABILITIES } from '@/lib/channel-capabilities';

/** Uniform status pill mapping for channels (plan 04 - statuses table, CHANNEL scope). */
export const CHANNEL_STATUS_REGISTRY: StatusRegistry<ChannelStatus> = {
  ACTIVE: { label: 'Active', tone: 'success' },
  PENDING: { label: 'Pending', tone: 'warning' },
  INACTIVE: { label: 'Inactive', tone: 'secondary' },
  ERROR: { label: 'Error', tone: 'destructive' },
};

/** Human labels for channel types - re-exported from the parity-pinned
 *  capability record (plan 32 / A7a; plan 34 / A7b adds `WEBCHAT`) so the
 *  label has exactly one source. */
export const CHANNEL_TYPE_LABELS: Record<ChannelType, string> = {
  WHATSAPP: CHANNEL_CAPABILITIES.WHATSAPP.label,
  FACEBOOK: CHANNEL_CAPABILITIES.FACEBOOK.label,
  INSTAGRAM: CHANNEL_CAPABILITIES.INSTAGRAM.label,
  WEBCHAT: CHANNEL_CAPABILITIES.WEBCHAT.label,
};

/** Type pill for the channels list "Type" column (plan 32 / A7a, AC-CHN-04;
 *  plan 34 / A7b adds `WEBCHAT`, AC-WEB-09) - one badge tone per channel
 *  type, distinct from the connection-status pill. `secondary` (neutral) for
 *  Web chat - it has no external provider brand to echo. */
export const CHANNEL_TYPE_REGISTRY: StatusRegistry<ChannelType> = {
  WHATSAPP: { label: 'WhatsApp', tone: 'success' },
  FACEBOOK: { label: 'Messenger', tone: 'info' },
  INSTAGRAM: { label: 'Instagram', tone: 'primary' },
  WEBCHAT: { label: 'Web chat', tone: 'secondary' },
};
