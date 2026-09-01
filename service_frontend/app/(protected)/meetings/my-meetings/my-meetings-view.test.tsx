/**
 * My meetings (S0) - AC-S0-6, AC-S0-7, AC-S0-8, AC-S0-9.
 *
 * Drives the page through the SERVICE boundary (the service module is mocked,
 * never fetch), so what is asserted is exactly what the user sees: the master
 * toggle starts off, the list only exists once it is on, a row's capture switch
 * writes the opt-out, and an opted-out row stays on screen.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingsEvent, MeetingsOptIn } from '@/types/meetings';

const optInState: { value: MeetingsOptIn } = {
  value: { enabled: false, lastSyncedAt: null },
};

const events: MeetingsEvent[] = [
  {
    id: 'evt-1',
    title: 'Weekly product sync',
    organiserEmail: 'ops@example.com',
    attendees: [
      { email: 'ops@example.com', displayName: 'Ops' },
      { email: 'demo@example.com', displayName: 'Demo User' },
    ],
    attendeeCount: 2,
    conferenceUrl: 'https://meet.google.com/abc-defg-hij',
    platform: 'meet',
    startsAt: '2026-09-01T02:00:00Z',
    endsAt: '2026-09-01T03:00:00Z',
    optedOut: false,
  },
  {
    id: 'evt-2',
    title: 'Vendor call',
    organiserEmail: 'partner@vendor.example',
    attendees: [{ email: 'partner@vendor.example', displayName: null }],
    attendeeCount: 1,
    conferenceUrl: 'https://us02web.zoom.us/j/8412345678',
    platform: 'zoom',
    startsAt: '2026-09-02T02:00:00Z',
    endsAt: null,
    optedOut: true,
  },
];

const getOptIn = vi.fn(async () => optInState.value);
const setOptIn = vi.fn(async (enabled: boolean) => {
  optInState.value = { enabled, lastSyncedAt: enabled ? '2026-09-01T00:00:00Z' : null };
  return optInState.value;
});
const listEvents = vi.fn(async () => (optInState.value.enabled ? events : []));
const setEventOptOut = vi.fn(async (id: string, optedOut: boolean) => {
  const row = events.find((e) => e.id === id)!;
  row.optedOut = optedOut;
  return { ...row };
});

vi.mock('@/services/meetings-service', () => ({
  meetingsService: {
    getOptIn: () => getOptIn(),
    setOptIn: (enabled: boolean) => setOptIn(enabled),
    listEvents: () => listEvents(),
    setEventOptOut: (id: string, optedOut: boolean) => setEventOptOut(id, optedOut),
    getSettings: vi.fn(),
    saveSettings: vi.fn(),
  },
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ status: 'authenticated', data: { user: { timezone: 'UTC' } } }),
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

// `vi.mock` is hoisted above imports, so a static import is already mocked.
import { MyMeetingsView } from './my-meetings-view';

describe('My meetings', () => {
  beforeEach(() => {
    optInState.value = { enabled: false, lastSyncedAt: null };
    events[0].optedOut = false;
    events[1].optedOut = true;
    setOptIn.mockClear();
    setEventOptOut.mockClear();
  });

  it('AC-S0-6/9: the master toggle is off by default and the empty state carries it as the CTA', async () => {
    render(<MyMeetingsView />);

    const toggle = await screen.findByRole('switch', { name: 'Record my meetings' });
    await waitFor(() => expect(toggle).not.toBeDisabled());
    expect(toggle).toHaveAttribute('data-state', 'unchecked');
    // Nothing is synced while it is off, so there is no list at all - the only
    // thing on offer is the toggle itself.
    expect(screen.getByRole('button', { name: 'Record my meetings' })).toBeInTheDocument();
    expect(screen.queryByText('Weekly product sync')).not.toBeInTheDocument();
  });

  it('AC-S0-7: switching the master toggle on lists the upcoming events with a capture switch each', async () => {
    const user = userEvent.setup();
    render(<MyMeetingsView />);

    const toggle = await screen.findByRole('switch', { name: 'Record my meetings' });
    await waitFor(() => expect(toggle).not.toBeDisabled());
    await user.click(toggle);

    await waitFor(() => expect(setOptIn).toHaveBeenCalledWith(true));
    expect(await screen.findByText('Weekly product sync')).toBeInTheDocument();
    expect(screen.getByText('ops@example.com')).toBeInTheDocument();
    expect(screen.getByText('Google Meet')).toBeInTheDocument();
    expect(screen.getByText('Zoom')).toBeInTheDocument();
    // Capture is ON by default for an event nobody opted out of.
    expect(
      screen.getByRole('switch', { name: 'Capture Weekly product sync' }),
    ).toHaveAttribute('data-state', 'checked');
  });

  it('AC-S0-8: switching a row off writes the opt-out and the row stays visible', async () => {
    const user = userEvent.setup();
    render(<MyMeetingsView />);

    const toggle = await screen.findByRole('switch', { name: 'Record my meetings' });
    await waitFor(() => expect(toggle).not.toBeDisabled());
    await user.click(toggle);
    await screen.findByText('Weekly product sync');

    await user.click(screen.getByRole('switch', { name: 'Capture Weekly product sync' }));

    await waitFor(() => expect(setEventOptOut).toHaveBeenCalledWith('evt-1', true));
    await waitFor(() =>
      expect(screen.getByRole('switch', { name: 'Capture Weekly product sync' })).toHaveAttribute(
        'data-state',
        'unchecked',
      ),
    );
    expect(screen.getByText('Weekly product sync')).toBeInTheDocument();
  });

  it('AC-S0-8: an already opted-out event is listed with its capture switch off', async () => {
    const user = userEvent.setup();
    render(<MyMeetingsView />);

    const toggle = await screen.findByRole('switch', { name: 'Record my meetings' });
    await waitFor(() => expect(toggle).not.toBeDisabled());
    await user.click(toggle);

    const row = await screen.findByText('Vendor call');
    expect(row).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Capture Vendor call' })).toHaveAttribute(
      'data-state',
      'unchecked',
    );
  });

  it('AC-S0-9: switching the master toggle back off empties the list', async () => {
    const user = userEvent.setup();
    render(<MyMeetingsView />);

    const toggle = await screen.findByRole('switch', { name: 'Record my meetings' });
    await waitFor(() => expect(toggle).not.toBeDisabled());
    await user.click(toggle);
    await screen.findByText('Weekly product sync');

    await user.click(toggle);
    await waitFor(() => expect(setOptIn).toHaveBeenLastCalledWith(false));
    await waitFor(() =>
      expect(screen.queryByText('Weekly product sync')).not.toBeInTheDocument(),
    );
    const empty = screen.getByRole('button', { name: 'Record my meetings' });
    expect(within(empty).getByText('Record my meetings')).toBeInTheDocument();
  });
});
