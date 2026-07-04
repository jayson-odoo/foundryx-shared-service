/** Status + priority registries for conversation threads (plan 05 inbox). */
import type { StatusRegistry } from '@/components/platform/status-badge';
import type { ThreadPriority, ThreadStatus } from '@/types/omnichannel';

export const THREAD_STATUS_REGISTRY: StatusRegistry<ThreadStatus> = {
  OPEN: { label: 'Open', tone: 'success' },
  SNOOZED: { label: 'Snoozed', tone: 'warning' },
  CLOSED: { label: 'Closed', tone: 'secondary' },
};

export const THREAD_PRIORITY_REGISTRY: StatusRegistry<ThreadPriority> = {
  LOW: { label: 'Low', tone: 'secondary' },
  MEDIUM: { label: 'Medium', tone: 'info' },
  HIGH: { label: 'High', tone: 'warning' },
  URGENT: { label: 'Urgent', tone: 'destructive' },
};
