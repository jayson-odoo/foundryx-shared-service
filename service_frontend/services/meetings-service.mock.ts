/**
 * PHASE 1 MOCK - in-memory meetings opt-in / events / settings (S0 plan §4).
 *
 * Retained for tunable frontend states and for tests; the shipped pages bind the
 * REAL service (`meetings-service.ts`). Delete once no longer referenced.
 */
import type {
  MeetingsBotRun,
  MeetingsEvent,
  MeetingsOptIn,
  MeetingsOptInInput,
  MeetingsSettings,
  MeetingsSettingsInput,
} from '@/types/meetings';
import type { MeetingsEventRange, MeetingsService } from './meetings-service';

function hoursFromNow(hours: number): string {
  return new Date(Date.now() + hours * 3_600_000).toISOString();
}

const seedEvents = (): MeetingsEvent[] => [
  {
    id: 'evt-1',
    title: 'Weekly product sync',
    organiserEmail: 'ops@example.com',
    attendees: [
      { email: 'ops@example.com', displayName: 'Ops' },
      { email: 'demo@example.com', displayName: 'Demo User' },
      { email: 'lead@example.com', displayName: 'Lead' },
    ],
    attendeeCount: 3,
    conferenceUrl: 'https://meet.google.com/abc-defg-hij',
    platform: 'meet',
    startsAt: hoursFromNow(3),
    endsAt: hoursFromNow(4),
    optedOut: false,
    meetingStatus: 'scheduled',
    statusReason: null,
  },
  {
    id: 'evt-2',
    title: 'Vendor call',
    organiserEmail: 'partner@vendor.example',
    attendees: [
      { email: 'partner@vendor.example', displayName: null },
      { email: 'demo@example.com', displayName: 'Demo User' },
    ],
    attendeeCount: 2,
    conferenceUrl: 'https://us02web.zoom.us/j/8412345678',
    platform: 'zoom',
    startsAt: hoursFromNow(26),
    endsAt: hoursFromNow(27),
    optedOut: true,
    meetingStatus: 'skipped',
    statusReason: 'opted_out',
  },
  {
    id: 'evt-3',
    title: null,
    organiserEmail: 'demo@example.com',
    attendees: [{ email: 'demo@example.com', displayName: 'Demo User' }],
    attendeeCount: 1,
    conferenceUrl: 'https://teams.microsoft.com/l/meetup-join/19%3ameeting',
    platform: 'teams',
    startsAt: hoursFromNow(72),
    endsAt: null,
    optedOut: false,
    meetingStatus: 'not_admitted',
    statusReason:
      'denied: the host never let the notetaker in and the 3 minute lobby wait ran out',
  },
];

const seedBotRuns = (): MeetingsBotRun[] => [
  {
    id: 'job-1',
    meetingId: 'mtg-1',
    meetingTitle: 'Weekly product sync',
    startsAt: hoursFromNow(-25),
    startedAt: hoursFromNow(-25),
    endedAt: hoursFromNow(-24),
    exitReason: 'room_empty',
    durationS: 3480,
    meetingStatus: 'ready',
  },
  {
    id: 'job-2',
    meetingId: 'mtg-2',
    meetingTitle: null,
    startsAt: hoursFromNow(-49),
    startedAt: hoursFromNow(-49),
    endedAt: hoursFromNow(-48),
    exitReason: 'denied',
    durationS: null,
    meetingStatus: 'not_admitted',
  },
];

const SERVICE_ACCOUNT = 'notetaker@foundryx.iam.gserviceaccount.com';

let optIn: MeetingsOptIn = {
  enabled: false,
  lastSyncedAt: null,
  calendarEmail: null,
  serviceAccountEmail: SERVICE_ACCOUNT,
};
let events: MeetingsEvent[] = seedEvents();
let botRuns: MeetingsBotRun[] = seedBotRuns();
let settings: MeetingsSettings = {
  calendarServiceAccountEmail: SERVICE_ACCOUNT,
  minutesLanguage: 'en',
  audioRetentionDays: 90,
  llmConnectionId: null,
  botDisplayName: null,
  consentMessage: null,
};

/** Test seam - put the mock back to its shipped starting state. */
export function resetMeetingsMock(): void {
  optIn = {
    enabled: false,
    lastSyncedAt: null,
    calendarEmail: null,
    serviceAccountEmail: SERVICE_ACCOUNT,
  };
  events = seedEvents();
  botRuns = seedBotRuns();
  settings = {
    calendarServiceAccountEmail: SERVICE_ACCOUNT,
    minutesLanguage: 'en',
    audioRetentionDays: 90,
    llmConnectionId: null,
    botDisplayName: null,
    consentMessage: null,
  };
}

export const mockMeetingsService: MeetingsService = {
  async getOptIn() {
    return { ...optIn };
  },
  async setOptIn(input: MeetingsOptInInput) {
    // A sync only ever runs for an opted-in user, so the timestamp appears
    // with the first ON and is left alone afterwards. An omitted calendar
    // address keeps the stored one; sent as null clears it back to the login.
    optIn = {
      ...optIn,
      enabled: input.enabled,
      lastSyncedAt: input.enabled
        ? (optIn.lastSyncedAt ?? new Date().toISOString())
        : optIn.lastSyncedAt,
      calendarEmail:
        'calendarEmail' in input ? (input.calendarEmail?.trim() || null) : optIn.calendarEmail,
    };
    return { ...optIn };
  },
  async listEvents(range?: MeetingsEventRange) {
    // Nothing is synced while the master toggle is off (AC-S0-9): existing rows
    // stay in the store, the caller just sees none.
    if (!optIn.enabled) return [];
    let rows = [...events];
    if (range?.from) rows = rows.filter((e) => e.startsAt >= range.from!);
    if (range?.to) rows = rows.filter((e) => e.startsAt <= range.to!);
    return rows.sort((a, b) => a.startsAt.localeCompare(b.startsAt));
  },
  async setEventOptOut(eventId: string, optedOut: boolean) {
    const row = events.find((e) => e.id === eventId);
    if (!row) throw new Error('Event not found.');
    row.optedOut = optedOut;
    return { ...row };
  },
  async listBotRuns(days = 7) {
    const cutoff = Date.now() - days * 86_400_000;
    return botRuns
      .filter((r) => new Date(r.startsAt).getTime() >= cutoff)
      .sort((a, b) => b.startsAt.localeCompare(a.startsAt));
  },
  async getSettings() {
    return { ...settings };
  },
  async saveSettings(input: MeetingsSettingsInput) {
    settings = { ...settings, ...input };
    return { ...settings };
  },
};
