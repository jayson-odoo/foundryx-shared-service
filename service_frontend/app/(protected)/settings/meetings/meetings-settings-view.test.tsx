/**
 * Settings → Meetings (S0) — AC-S0-4, AC-S0-5, AC-S0-14 (structure half).
 *
 * The connection cards must offer exactly the two meetings kinds and route into
 * the SHARED integrations form with the provider preselected — the page never
 * re-implements a connection editor, so nothing here asserts field rendering.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Connection } from '@/types/integration';
import type { MeetingsSettings } from '@/types/meetings';

const settingsState: { value: MeetingsSettings } = {
  value: {
    minutesLanguage: 'en',
    audioRetentionDays: 90,
    llmConnectionId: null,
    botDisplayName: null,
    consentMessage: null,
  },
};

const connections: { value: Connection[] } = { value: [] };

const saveSettings = vi.fn(async (input: Partial<MeetingsSettings>) => {
  settingsState.value = { ...settingsState.value, ...input };
  return settingsState.value;
});

vi.mock('@/services/meetings-service', () => ({
  meetingsService: {
    getOptIn: vi.fn(),
    setOptIn: vi.fn(),
    listEvents: vi.fn(),
    setEventOptOut: vi.fn(),
    getSettings: async () => settingsState.value,
    saveSettings: (input: Partial<MeetingsSettings>) => saveSettings(input),
  },
}));

vi.mock('@/services/integration-service', () => ({
  integrationService: {
    list: async () => ({ data: connections.value, total: connections.value.length, page: 0 }),
  },
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));

// `vi.mock` is hoisted above imports, so a static import is already mocked.
import { MeetingsSettingsView } from './meetings-settings-view';

function connection(overrides: Partial<Connection>): Connection {
  return {
    id: 'conn-1',
    tenantId: 't1',
    provider: 'google_dwd',
    type: 'calendar',
    name: 'Google Calendar',
    config: {},
    status: 'ACTIVE',
    isActive: true,
    lastTestedAt: null,
    lastError: null,
    rateLimitPerMinute: 30,
    createdAt: '2026-08-01T00:00:00Z',
    updatedAt: '2026-08-01T00:00:00Z',
    ...overrides,
  };
}

describe('Settings → Meetings', () => {
  beforeEach(() => {
    connections.value = [];
    settingsState.value = {
      minutesLanguage: 'en',
      audioRetentionDays: 90,
      llmConnectionId: null,
      botDisplayName: null,
      consentMessage: null,
    };
    saveSettings.mockClear();
  });

  it('AC-S0-4/5: offers both meetings connection kinds, deep-linked to the shared form', async () => {
    render(<MeetingsSettingsView />);

    const links = await screen.findAllByRole('link', { name: 'Connect' });
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute(
      'href',
      '/settings/integrations/new?provider=google_dwd',
    );
    expect(links[1]).toHaveAttribute(
      'href',
      '/settings/integrations/new?provider=meet_bot',
    );
    expect(screen.getByText('Google Calendar')).toBeInTheDocument();
    expect(screen.getByText('Notetaker account')).toBeInTheDocument();
  });

  it('AC-S0-4: an existing connection shows its health and opens the shared form', async () => {
    connections.value = [connection({ id: 'conn-9', status: 'ERROR' })];
    render(<MeetingsSettingsView />);

    const open = await screen.findByRole('link', { name: 'Open' });
    expect(open).toHaveAttribute('href', '/settings/integrations/conn-9');
    expect(screen.getByText('Error')).toBeInTheDocument();
    // The bot account has no connection yet, so it still offers Connect.
    expect(screen.getByRole('link', { name: 'Connect' })).toHaveAttribute(
      'href',
      '/settings/integrations/new?provider=meet_bot',
    );
  });

  it('stores the tenant settings through the service boundary', async () => {
    const user = userEvent.setup();
    render(<MeetingsSettingsView />);

    const botName = await screen.findByLabelText('Notetaker display name');
    await user.clear(botName);
    await user.type(botName, 'Minutes bot');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(saveSettings).toHaveBeenCalledWith({
        minutesLanguage: 'en',
        audioRetentionDays: 90,
        botDisplayName: 'Minutes bot',
        consentMessage: null,
      }),
    );
  });

  it('offers "Keep" instead of asking for a magic retention number', async () => {
    const user = userEvent.setup();
    render(<MeetingsSettingsView />);

    await user.click(await screen.findByRole('combobox', { name: 'Recordings' }));
    expect(await screen.findByText('Keep')).toBeInTheDocument();
    // '90 days' is both the trigger's current value and its option row.
    expect(screen.getAllByText('90 days').length).toBeGreaterThan(0);
  });
});
