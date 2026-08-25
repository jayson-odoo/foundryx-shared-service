/**
 * Real meetings service — talks to FastAPI via the shared api-client.
 *
 * Reads/writes on the caller's own opt-in and events are gated `meetings.view`;
 * the tenant settings are gated `meetings.settings.manage`.
 */
import { apiFetch } from '@/lib/api-client';
import type {
  MeetingsBotRun,
  MeetingsEvent,
  MeetingsOptIn,
  MeetingsOptInInput,
  MeetingsSettings,
  MeetingsSettingsInput,
} from '@/types/meetings';
import type { MeetingsEventRange, MeetingsService } from './meetings-service';

interface EventListResponse {
  data: MeetingsEvent[];
}

interface BotRunListResponse {
  data: MeetingsBotRun[];
}

function eventsPath(range?: MeetingsEventRange): string {
  const params = new URLSearchParams();
  if (range?.from) params.set('from', range.from);
  if (range?.to) params.set('to', range.to);
  const query = params.toString();
  return query ? `/meetings/events?${query}` : '/meetings/events';
}

export const realMeetingsService: MeetingsService = {
  getOptIn() {
    return apiFetch<MeetingsOptIn>('/meetings/optin');
  },
  setOptIn(input: MeetingsOptInInput) {
    return apiFetch<MeetingsOptIn>('/meetings/optin', {
      method: 'PUT',
      body: JSON.stringify(input),
    });
  },
  async listEvents(range?: MeetingsEventRange) {
    const res = await apiFetch<EventListResponse>(eventsPath(range));
    return res.data;
  },
  setEventOptOut(eventId: string, optedOut: boolean) {
    return apiFetch<MeetingsEvent>(
      `/meetings/events/${encodeURIComponent(eventId)}/opt-out`,
      { method: 'PUT', body: JSON.stringify({ optedOut }) },
    );
  },
  async listBotRuns(days = 7) {
    const res = await apiFetch<BotRunListResponse>(
      `/meetings/bot-runs?days=${encodeURIComponent(String(days))}`,
    );
    return res.data;
  },
  getSettings() {
    return apiFetch<MeetingsSettings>('/meetings/settings');
  },
  saveSettings(input: MeetingsSettingsInput) {
    return apiFetch<MeetingsSettings>('/meetings/settings', {
      method: 'PUT',
      body: JSON.stringify(input),
    });
  },
};
