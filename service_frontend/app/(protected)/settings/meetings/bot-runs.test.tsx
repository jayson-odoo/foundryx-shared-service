/**
 * Settings → Meetings, Bot section - AC-S2-12.
 *
 * Drives the page through the SERVICE boundary, so what is asserted is what the
 * tenant admin sees: a week of runs with meeting, start, end, exit reason and
 * duration, plus the notetaker connection's own status and last success.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Connection } from '@/types/integration';
import type { MeetingsBotRun, MeetingsSettings } from '@/types/meetings';
import { formatDuration } from './use-bot-runs-list-config';

const SERVICE_ACCOUNT = 'notetaker@proj.iam.gserviceaccount.com';

const settingsValue: MeetingsSettings = {
  calendarServiceAccountEmail: SERVICE_ACCOUNT,
  minutesLanguage: 'en',
  audioRetentionDays: 90,
  llmConnectionId: null,
  botDisplayName: null,
  consentMessage: null,
};

const runs: { value: MeetingsBotRun[] } = { value: [] };
const connections: { value: Connection[] } = { value: [] };
const listBotRuns = vi.fn(async (days?: number) => (days ? runs.value : runs.value));

vi.mock('@/services/meetings-service', () => ({
  meetingsService: {
    getOptIn: vi.fn(),
    setOptIn: vi.fn(),
    listEvents: vi.fn(),
    setEventOptOut: vi.fn(),
    listBotRuns: (days?: number) => listBotRuns(days),
    getSettings: vi.fn(async () => settingsValue),
    saveSettings: vi.fn(async () => settingsValue),
  },
}));

vi.mock('@/services/integration-service', () => ({
  integrationService: {
    list: vi.fn(async () => ({ data: connections.value, total: connections.value.length })),
  },
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ status: 'authenticated', data: { user: { timezone: 'UTC' } } }),
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true }),
}));

vi.mock('@/hooks/use-view-preferences', () => ({
  useViewPreferences: () => ({
    isLoaded: true,
    columnOrder: [],
    columnVisibility: {},
    columnSizing: {},
    setColumnOrder: () => {},
    setColumnVisibility: () => {},
    setColumnSizing: () => {},
  }),
}));

import { MeetingsSettingsView } from './meetings-settings-view';

function connection(overrides: Partial<Connection>): Connection {
  return {
    id: 'conn-1',
    tenantId: 't1',
    provider: 'meet_bot',
    type: 'meeting_bot',
    name: 'Notetaker',
    config: {},
    status: 'UNVERIFIED',
    lastTestedAt: null,
    lastError: null,
    isActive: true,
    rateLimitPerMinute: 30,
    createdAt: '2026-08-01T00:00:00Z',
    updatedAt: '2026-08-01T00:00:00Z',
    ...overrides,
  } as Connection;
}

describe('Settings → Meetings, Bot runs', () => {
  beforeEach(() => {
    runs.value = [];
    connections.value = [];
    listBotRuns.mockClear();
  });

  it('AC-S2-12: asks for the last 7 days', async () => {
    render(<MeetingsSettingsView />);
    await waitFor(() => expect(listBotRuns).toHaveBeenCalledWith(7));
  });

  it('AC-S2-12: a run shows the meeting, when it ran, why it ended and how long', async () => {
    runs.value = [
      {
        id: 'job-1',
        meetingId: 'mtg-1',
        meetingTitle: 'Weekly product sync',
        startsAt: '2026-08-24T02:00:00Z',
        startedAt: '2026-08-24T02:00:00Z',
        endedAt: '2026-08-24T02:58:00Z',
        exitReason: 'room_empty',
        durationS: 3480,
        meetingStatus: 'ready',
      },
    ];
    render(<MeetingsSettingsView />);

    expect(await screen.findByText('Weekly product sync')).toBeInTheDocument();
    expect(screen.getAllByText('room_empty').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Ready').length).toBeGreaterThan(0);
    expect(screen.getAllByText('58m 00s').length).toBeGreaterThan(0);
  });

  it('AC-S2-12: a run that never recorded shows no duration rather than a zero', async () => {
    runs.value = [
      {
        id: 'job-2',
        meetingId: 'mtg-2',
        meetingTitle: 'Vendor call',
        startsAt: '2026-08-24T02:00:00Z',
        startedAt: '2026-08-24T02:00:00Z',
        endedAt: '2026-08-24T02:03:00Z',
        exitReason: 'denied',
        durationS: null,
        meetingStatus: 'not_admitted',
      },
    ];
    render(<MeetingsSettingsView />);

    expect(await screen.findByText('Vendor call')).toBeInTheDocument();
    expect(screen.getAllByText('Not admitted').length).toBeGreaterThan(0);
    expect(screen.getAllByText('-').length).toBeGreaterThan(0);
  });

  it('AC-S2-12: the notetaker account stays Unverified until a run signs in', async () => {
    connections.value = [connection({ status: 'UNVERIFIED', lastTestedAt: null })];
    render(<MeetingsSettingsView />);

    expect(await screen.findByText('Unverified')).toBeInTheDocument();
  });

  it('AC-S2-12: once a run has signed in the account is Connected, with the time', async () => {
    connections.value = [
      connection({ status: 'ACTIVE', lastTestedAt: '2026-08-24T02:00:00Z' }),
    ];
    render(<MeetingsSettingsView />);

    expect(await screen.findByText('Connected')).toBeInTheDocument();
    expect(await screen.findByText(/24 Aug 2026/)).toBeInTheDocument();
  });
});

describe('formatDuration', () => {
  it('reads a call length the way an operator does', () => {
    expect(formatDuration(null)).toBe('-');
    expect(formatDuration(42)).toBe('42s');
    expect(formatDuration(3480)).toBe('58m 00s');
    expect(formatDuration(3720)).toBe('1h 02m');
  });
});
