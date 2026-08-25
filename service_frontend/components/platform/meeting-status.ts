import type { StatusRegistry } from '@/components/platform/status-badge';
import type { MeetingStatus } from '@/types/meetings';

/**
 * Status pill mapping for a meeting (S2, AC-S2-11). ONE registry, shared by My
 * meetings and by Settings -> Meetings, so a status never reads two ways.
 *
 * The tones carry the meaning: everything on the happy path is neutral or
 * positive, a state that needs someone to look is a warning, and only a genuine
 * failure is destructive.
 */
export const MEETING_STATUS_REGISTRY: StatusRegistry<MeetingStatus> = {
  scheduled: { label: 'Scheduled', tone: 'secondary' },
  joining: { label: 'Joining', tone: 'info' },
  in_lobby: { label: 'In lobby', tone: 'info' },
  recording: { label: 'Recording', tone: 'primary' },
  processing: { label: 'Processing', tone: 'info' },
  ready: { label: 'Ready', tone: 'success' },
  not_admitted: { label: 'Not admitted', tone: 'warning' },
  failed: { label: 'Failed', tone: 'destructive' },
  skipped: { label: 'Skipped', tone: 'secondary' },
};
