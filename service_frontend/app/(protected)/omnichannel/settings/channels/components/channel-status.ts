import type { StatusRegistry } from '@/components/platform/status-badge';
import type { ChannelStatus, ChannelType } from '@/types/omnichannel';

/** Uniform status pill mapping for channels (plan 04 - statuses table, CHANNEL scope). */
export const CHANNEL_STATUS_REGISTRY: StatusRegistry<ChannelStatus> = {
  ACTIVE: { label: 'Active', tone: 'success' },
  PENDING: { label: 'Pending', tone: 'warning' },
  INACTIVE: { label: 'Inactive', tone: 'secondary' },
  ERROR: { label: 'Error', tone: 'destructive' },
};

/** Human labels for channel types (MVP builds WHATSAPP; others are later adapters). */
export const CHANNEL_TYPE_LABELS: Record<ChannelType, string> = {
  WHATSAPP: 'WhatsApp',
  FACEBOOK: 'Messenger',
  INSTAGRAM: 'Instagram',
  DOUYIN: 'Douyin',
  XIAOHONGSHU: 'Xiaohongshu',
};
