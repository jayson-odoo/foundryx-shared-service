/**
 * My meetings with the Foundryx UIUX switch on (slice W4-ACCOUNT): the master
 * switch, the Calendar address and a meeting's Capture switch send exactly
 * what the switch-off page sends for the same input; each ends with a done
 * toast whose Undo sends the earlier value back; with recording off the red
 * action turns it on. Switch off is pinned by
 * `__parity__/my-meetings.parity.test.tsx`.
 */
import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingsEvent, MeetingsOptIn, MeetingsOptInInput } from '@/types/meetings';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import MyMeetingsPage from './page';

const state = vi.hoisted(() => ({ optIn: null as unknown as MeetingsOptIn }));
const EVENT: MeetingsEvent = {
  id: 'evt-1',
  title: 'Weekly product sync',
  organiserEmail: 'ops@example.com',
  attendees: [{ email: 'ops@example.com', displayName: 'Ops' }],
  attendeeCount: 1,
  conferenceUrl: 'https://meet.google.com/abc-defg-hij',
  platform: 'meet',
  startsAt: '2026-09-01T02:00:00Z',
  endsAt: '2026-09-01T03:00:00Z',
  optedOut: false,
  meetingStatus: 'scheduled',
  statusReason: null,
};
const svc = vi.hoisted(() => ({ setOptIn: vi.fn(), setEventOptOut: vi.fn() }));
const toasts = vi.hoisted(() => ({ fxDone: vi.fn(), error: vi.fn(), success: vi.fn() }));

vi.mock('@/lib/toast', async (orig) => {
  const real = (await orig()) as { toast: Record<string, unknown> };
  return { toast: { ...real.toast, ...toasts } };
});
vi.mock('@/services/meetings-service', () => ({
  meetingsService: {
    getOptIn: vi.fn(async () => state.optIn),
    setOptIn: (input: MeetingsOptInInput) => svc.setOptIn(input),
    listEvents: vi.fn(async () => [{ ...EVENT }]),
    setEventOptOut: (id: string, optedOut: boolean) => svc.setEventOptOut(id, optedOut),
    getSettings: vi.fn(),
    saveSettings: vi.fn(),
  },
}));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/meetings/my-meetings'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Demo User', permissions: [], timezone: 'Asia/Kuala_Lumpur' } },
    status: 'authenticated',
  }),
}));
vi.mock('next-themes', () => ({ useTheme: () => ({ theme: 'light', setTheme: vi.fn() }) }));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: ReactNode }) => children,
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
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

function look(on: boolean) {
  return function Look({ children }: { children: ReactNode }) {
    return (
      <SettingsProvider>
        <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
          {children}
        </FxProvider>
      </SettingsProvider>
    );
  };
}

function fresh(enabled: boolean, calendarEmail: string | null = null) {
  state.optIn = {
    enabled,
    lastSyncedAt: null,
    calendarEmail,
    serviceAccountEmail: 'notetaker@proj.iam.gserviceaccount.com',
  };
}

beforeEach(() => {
  fresh(false);
  svc.setOptIn.mockReset().mockImplementation(async (input: MeetingsOptInInput) => {
    state.optIn = {
      ...state.optIn,
      enabled: input.enabled,
      calendarEmail: 'calendarEmail' in input ? (input.calendarEmail ?? null) : state.optIn.calendarEmail,
    };
    return state.optIn;
  });
  svc.setEventOptOut
    .mockReset()
    .mockImplementation(async (id: string, optedOut: boolean) => ({ ...EVENT, id, optedOut }));
  Object.values(toasts).forEach((fn) => fn.mockReset());
});
afterEach(() => resetPageActionsForTests());

const calendarField = () => document.getElementById('meetings-calendar-email') as HTMLInputElement;

async function openPage(on: boolean) {
  const view = render(<MyMeetingsPage />, { wrapper: look(on) });
  const toggle = await screen.findByRole('switch', { name: 'Record my meetings' });
  await waitFor(() => expect(toggle).toBeEnabled());
  return view;
}

async function bothLooks(
  spy: ReturnType<typeof vi.fn>,
  setup: () => void,
  act: (on: boolean) => Promise<void>,
) {
  const calls: unknown[][][] = [];
  for (const on of [false, true]) {
    setup();
    spy.mockClear();
    resetPageActionsForTests();
    const view = await openPage(on);
    await act(on);
    await waitFor(() => expect(spy).toHaveBeenCalled());
    calls.push(spy.mock.calls.slice());
    view.unmount();
  }
  return calls;
}

describe('the same writes in both looks', () => {
  it('turning recording on with the switch', async () => {
    const [off, on] = await bothLooks(svc.setOptIn, () => fresh(false), async () => {
      fireEvent.click(screen.getByRole('switch', { name: 'Record my meetings' }));
    });
    expect(on).toEqual(off);
    expect(on).toEqual([[{ enabled: true }]]);
  });

  it('turning recording on from the empty state (switch-off button, switch-on red action)', async () => {
    const [off, on] = await bothLooks(svc.setOptIn, () => fresh(false), async () => {
      const buttons = screen.getAllByRole('button', { name: 'Record my meetings' });
      fireEvent.click(buttons[buttons.length - 1]);
    });
    expect(on).toEqual(off);
  });

  it.each([
    ['a new address', 'me@gmail.com', null],
    ['an address with spaces round it', '  me@gmail.com ', null],
    ['blank (back to the sign-in email)', '', 'old@gmail.com'],
  ])('the calendar: %s', async (_n, typed, stored) => {
    const [off, on] = await bothLooks(svc.setOptIn, () => fresh(true, stored), async () => {
      await screen.findAllByText('Weekly product sync');
      const field = calendarField();
      fireEvent.change(field, { target: { value: typed } });
      fireEvent.blur(field);
    });
    expect(on).toEqual(off);
  });

  it('turning a meeting\'s capture off', async () => {
    const [off, on] = await bothLooks(svc.setEventOptOut, () => fresh(true), async () => {
      await screen.findAllByText('Weekly product sync');
      fireEvent.click(screen.getByRole('switch', { name: 'Capture Weekly product sync' }));
    });
    expect(on).toEqual(off);
    expect(on).toEqual([['evt-1', true]]);
  });
});

describe('switch on', () => {
  it('a calendar that is not an email is not sent and says why under the field', async () => {
    fresh(true);
    await openPage(true);
    const field = calendarField();
    fireEvent.change(field, { target: { value: 'not-an-email' } });
    fireEvent.blur(field);
    expect(await screen.findByText('Enter a valid email address.')).toBeInTheDocument();
    expect(field).toHaveValue('not-an-email');
    expect(svc.setOptIn).not.toHaveBeenCalled();
    expect(toasts.error).not.toHaveBeenCalled();
  });

  it('Undo after turning recording on turns it back off', async () => {
    await openPage(true);
    fireEvent.click(screen.getByRole('switch', { name: 'Record my meetings' }));
    await waitFor(() => expect(toasts.fxDone).toHaveBeenCalled());
    const done = toasts.fxDone.mock.calls[0][0];
    expect(done.what).toBe('Recording turned on for your meetings');
    svc.setOptIn.mockClear();
    done.undo();
    await waitFor(() => expect(svc.setOptIn).toHaveBeenCalledWith({ enabled: false }));
  });

  it('Undo after a calendar change sends the earlier address back', async () => {
    fresh(true, 'old@gmail.com');
    await openPage(true);
    const field = calendarField();
    fireEvent.change(field, { target: { value: 'me@gmail.com' } });
    fireEvent.blur(field);
    await waitFor(() => expect(toasts.fxDone).toHaveBeenCalled());
    const done = toasts.fxDone.mock.calls[0][0];
    expect(done.what).toBe('Calendar set to me@gmail.com');
    svc.setOptIn.mockClear();
    done.undo();
    await waitFor(() =>
      expect(svc.setOptIn).toHaveBeenCalledWith({ enabled: true, calendarEmail: 'old@gmail.com' }),
    );
  });

  it('Undo after turning capture off turns it back on', async () => {
    fresh(true);
    await openPage(true);
    await screen.findAllByText('Weekly product sync');
    fireEvent.click(screen.getByRole('switch', { name: 'Capture Weekly product sync' }));
    await waitFor(() => expect(toasts.fxDone).toHaveBeenCalled());
    const done = toasts.fxDone.mock.calls[0][0];
    expect(done.what).toBe('Capture turned off for Weekly product sync');
    svc.setEventOptOut.mockClear();
    done.undo();
    await waitFor(() => expect(svc.setEventOptOut).toHaveBeenCalledWith('evt-1', false));
  });

  it('shows 12-hour times in the viewer zone', async () => {
    fresh(true);
    await openPage(true);
    await screen.findAllByText('Weekly product sync');
    expect(document.body.textContent).toContain('2026, 10:00 am to 11:00 am');
  });

  it('with recording off, the empty state is one line and the red action turns it on', async () => {
    await openPage(true);
    expect(screen.getByText('No meetings while recording is off.')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Record my meetings' })).toHaveLength(1);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Record my meetings' }));
    await waitFor(() => expect(svc.setOptIn).toHaveBeenCalledWith({ enabled: true }));
  });
});
