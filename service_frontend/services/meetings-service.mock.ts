/**
 * PHASE 1 MOCK - in-memory meetings opt-in / events / settings (S0 plan §4).
 *
 * Retained for tunable frontend states and for tests; the shipped pages bind the
 * REAL service (`meetings-service.ts`). Delete once no longer referenced.
 */
import type {
  MeetingsEvent,
  MeetingsOptIn,
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
  },
];

let optIn: MeetingsOptIn = { enabled: false, lastSyncedAt: null };
let events: MeetingsEvent[] = seedEvents();
let settings: MeetingsSettings = {
  minutesLanguage: 'en',
  audioRetentionDays: 90,
  llmConnectionId: null,
  botDisplayName: null,
  consentMessage: null,
};

/** Test seam - put the mock back to its shipped starting state. */
export function resetMeetingsMock(): void {
  optIn = { enabled: false, lastSyncedAt: null };
  events = seedEvents();
  settings = {
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
  async setOptIn(enabled: boolean) {
    // A sync only ever runs for an opted-in user, so the timestamp appears
    // with the first ON and is left alone afterwards.
    optIn = {
      enabled,
      lastSyncedAt: enabled ? (optIn.lastSyncedAt ?? new Date().toISOString()) : optIn.lastSyncedAt,
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
  async getSettings() {
    return { ...settings };
  },
  async saveSettings(input: MeetingsSettingsInput) {
    settings = { ...settings, ...input };
    return { ...settings };
  },
};
