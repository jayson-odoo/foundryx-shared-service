/**
 * Meetings module wire types (S0 — calendar opt-in).
 *
 * These mirror the backend schemas one-for-one (`modules/meetings/schemas.py`);
 * the wire is camelCase and every timestamp is a Z-suffixed UTC ISO-8601 string
 * that the UI renders through `useDatetime()`, never `new Date(iso)`.
 */

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

/** Write shape for the master toggle — an omitted key keeps its stored value. */
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

/** Every settings field is optional on write — an omitted key keeps its value.
 *  `calendarServiceAccountEmail` is read-only, so it is not writable. */
export type MeetingsSettingsInput = Partial<
  Omit<MeetingsSettings, 'calendarServiceAccountEmail'>
>;
