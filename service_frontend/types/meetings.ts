/**
 * Meetings module wire types (S0 - calendar opt-in).
 *
 * These mirror the backend schemas one-for-one (`modules/meetings/schemas.py`);
 * the wire is camelCase and every timestamp is a Z-suffixed UTC ISO-8601 string
 * that the UI renders through `useDatetime()`, never `new Date(iso)`.
 */

/**
 * A meeting's lifecycle (S2). A plain machine-driven enum, never the status
 * engine: no tenant edits these and no transition is a human action.
 */
export type MeetingStatus =
  | 'scheduled'
  | 'joining'
  | 'in_lobby'
  | 'recording'
  | 'processing'
  | 'transcribed'
  | 'ready'
  | 'failed'
  | 'not_admitted'
  | 'skipped';

/** Conference platform recognised on a calendar event's link. */
export type MeetingPlatform = 'meet' | 'zoom' | 'teams' | 'other';

/** One invitee of a calendar event. */
export interface MeetingAttendee {
  email: string;
  displayName: string | null;
}

/** The caller's master toggle (spine M6). */
export interface MeetingsOptIn {
  enabled: boolean;
  /** When this user's calendar was last read; null until the first sync. */
  lastSyncedAt: string | null;
  /** Which calendar to read; null = the caller's own login email. */
  calendarEmail: string | null;
  /** The address a calendar has to be shared with; null = no connection yet. */
  serviceAccountEmail: string | null;
}

/** Write shape for the master toggle - an omitted key keeps its stored value. */
export interface MeetingsOptInInput {
  enabled: boolean;
  calendarEmail?: string | null;
}

/** One upcoming calendar event carrying a conference link. */
export interface MeetingsEvent {
  id: string;
  title: string | null;
  organiserEmail: string | null;
  attendees: MeetingAttendee[];
  attendeeCount: number;
  conferenceUrl: string;
  platform: MeetingPlatform;
  startsAt: string;
  endsAt: string | null;
  /** True once the user has switched this single event off. */
  optedOut: boolean;
  /** Where the shared meeting behind this event has got to (S2). */
  meetingStatus: MeetingStatus;
  /** Why it failed / was not admitted / was skipped; null otherwise. */
  statusReason: string | null;
}

/** One bot run, for the tenant admin's ops list (AC-S2-12). */
export interface MeetingsBotRun {
  /** The `background_jobs` row id. */
  id: string;
  meetingId: string;
  meetingTitle: string | null;
  startsAt: string;
  /** When the container actually started; null while the job is still queued. */
  startedAt: string | null;
  endedAt: string | null;
  /** The container's own exit word (`room_empty`, `denied`, `error:…`, …). */
  exitReason: string | null;
  /** Recorded seconds; null unless the bot got as far as recording. */
  durationS: number | null;
  /** The meeting's status after the run. */
  meetingStatus: MeetingStatus;
}

/** Tenant-wide module settings. */
export interface MeetingsSettings {
  /** Read-only: the calendar connection's own service-account address. */
  calendarServiceAccountEmail: string | null;
  minutesLanguage: string;
  /** 0 = keep recordings forever. */
  audioRetentionDays: number;
  llmConnectionId: string | null;
  botDisplayName: string | null;
  consentMessage: string | null;
}

/** Every settings field is optional on write - an omitted key keeps its value.
 *  `calendarServiceAccountEmail` is read-only, so it is not writable. */
export type MeetingsSettingsInput = Partial<
  Omit<MeetingsSettings, 'calendarServiceAccountEmail'>
>;
