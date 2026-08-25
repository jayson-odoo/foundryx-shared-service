/**
 * Meetings service — the boundary the UI talks to (S0 plan §4/§5).
 *
 * The interface IS the backend contract (`/meetings/optin`, `/meetings/events`,
 * `/meetings/settings`). Frontend-first was built against `meetings-service.mock`;
 * the shipped pages bind the REAL api-client implementation — the swap is the ONE
 * line at the bottom of this file.
 */
import type {
  MeetingsEvent,
  MeetingsOptIn,
  MeetingsOptInInput,
  MeetingsSettings,
  MeetingsSettingsInput,
} from '@/types/meetings';
import { realMeetingsService } from './meetings-service.real';

/** Window of upcoming events to read; both ends are ISO-8601 UTC. */
export interface MeetingsEventRange {
  from?: string;
  to?: string;
}

export interface MeetingsService {
  /** The caller's own master toggle. */
  getOptIn(): Promise<MeetingsOptIn>;
  /** Flip the caller's master toggle, and optionally point it at a calendar. */
  setOptIn(input: MeetingsOptInInput): Promise<MeetingsOptIn>;
  /** The caller's upcoming events that carry a conference link. */
  listEvents(range?: MeetingsEventRange): Promise<MeetingsEvent[]>;
  /** Switch a single event out of (or back into) capture. */
  setEventOptOut(eventId: string, optedOut: boolean): Promise<MeetingsEvent>;
  /** Tenant-wide module settings. */
  getSettings(): Promise<MeetingsSettings>;
  saveSettings(input: MeetingsSettingsInput): Promise<MeetingsSettings>;
}

// Phase 2 swap done — the mock is retained in *.mock.ts for tunable states.
export const meetingsService: MeetingsService = realMeetingsService;
