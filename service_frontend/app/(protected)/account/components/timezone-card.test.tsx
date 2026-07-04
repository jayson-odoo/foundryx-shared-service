/**
 * Timezone preference card (plan sprint-2/05 Phase A) — picker renders the
 * browser-default fallback, saving goes through the service boundary, and the
 * picked zone sticks.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TimezoneCard } from './timezone-card';

const sessionUpdate = vi.fn(async () => null);
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    status: 'authenticated',
    update: sessionUpdate,
    data: { user: { timezone: null } },
  }),
}));

const saveTimezone = vi.fn(async (tz: string | null) => void tz);
vi.mock('@/services/profile-preferences-service', () => ({
  profilePreferencesService: {
    saveTimezone: (tz: string | null) => saveTimezone(tz),
  },
}));

describe('TimezoneCard', () => {
  beforeEach(() => {
    saveTimezone.mockClear();
    sessionUpdate.mockClear();
  });

  it('defaults to the browser timezone option', () => {
    render(<TimezoneCard />);
    expect(screen.getByText(/Browser default —/)).toBeInTheDocument();
  });

  it('saves a picked zone through the service and refreshes the session', async () => {
    const user = userEvent.setup();
    render(<TimezoneCard />);

    await user.click(screen.getByRole('combobox', { name: 'Timezone' }));
    const search = screen.getByPlaceholderText('Search timezones…');
    await user.type(search, 'Singapore');
    await user.click(await screen.findByText(/Asia\/Singapore/));

    await waitFor(() => expect(saveTimezone).toHaveBeenCalledWith('Asia/Singapore'));
    expect(sessionUpdate).toHaveBeenCalled();
    // picker now shows the stored zone
    expect(
      screen.getByRole('combobox', { name: 'Timezone' }),
    ).toHaveTextContent(/Asia\/Singapore/);
  });

  it('clears back to the browser default with null', async () => {
    const user = userEvent.setup();
    render(<TimezoneCard />);

    await user.click(screen.getByRole('combobox', { name: 'Timezone' }));
    await user.type(screen.getByPlaceholderText('Search timezones…'), 'Tokyo');
    await user.click(await screen.findByText(/Asia\/Tokyo/));
    await waitFor(() => expect(saveTimezone).toHaveBeenCalledWith('Asia/Tokyo'));

    await user.click(screen.getByRole('combobox', { name: 'Timezone' }));
    await user.type(
      screen.getByPlaceholderText('Search timezones…'),
      'Browser default',
    );
    await user.click(await screen.findByText(/Browser default —/));
    await waitFor(() => expect(saveTimezone).toHaveBeenCalledWith(null));
  });
});
