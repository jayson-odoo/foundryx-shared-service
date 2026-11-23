/**
 * Switch-off parity for My meetings (Foundryx UIUX slice W4-ACCOUNT): the page
 * with recording off (the empty state), with it on and two upcoming meetings
 * (one opted out, with a reason), and with a load error, rendered with the
 * switch OFF. Recorded on the code as it was before the slice; a change that
 * needs one of these snapshots updated is wrong by definition.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import type { MeetingsEvent, MeetingsOptIn } from '@/types/meetings';
import MyMeetingsPage from '../page';

const state = vi.hoisted(() => ({
  optIn: null as unknown as MeetingsOptIn,
  fail: false,
}));

const EVENTS: MeetingsEvent[] = [
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
    meetingStatus: 'scheduled',
    statusReason: null,
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
    meetingStatus: 'not_admitted',
    statusReason: 'denied: the host never let the notetaker in',
  },
];

vi.mock('@/services/meetings-service', () => ({
  meetingsService: {
    getOptIn: vi.fn(async () => {
      if (state.fail) throw new Error('Could not reach the calendar.');
      return state.optIn;
    }),
    setOptIn: vi.fn(),
    listEvents: vi.fn(async () => EVENTS),
    setEventOptOut: vi.fn(),
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
    data: { user: { name: 'Demo User', permissions: [], timezone: 'UTC' } },
    status: 'authenticated',
  }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => children,
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

function stable(root: Element): string {
  const seen = new Map<string, string>();
  return parityHtml(root).replace(/_r_[0-9a-z]+_/g, (id) => {
    let name = seen.get(id);
    if (!name) {
      name = `_rid${seen.size}_`;
      seen.set(id, name);
    }
    return name;
  });
}

function renderPage() {
  return render(
    <SettingsProvider>
      <MyMeetingsPage />
    </SettingsProvider>,
  );
}

beforeEach(() => {
  state.fail = false;
  state.optIn = {
    enabled: false,
    lastSyncedAt: null,
    calendarEmail: null,
    serviceAccountEmail: 'notetaker@proj.iam.gserviceaccount.com',
  };
});

describe('parity (switch off): My meetings', () => {
  it('recording off', async () => {
    const { container } = renderPage();
    const toggle = await screen.findByRole('switch', { name: 'Record my meetings' });
    await waitFor(() => expect(toggle).toBeEnabled());
    expect(stable(container)).toMatchSnapshot();
  });

  it('recording on, with two meetings', async () => {
    state.optIn = { ...state.optIn, enabled: true, calendarEmail: 'me@gmail.com' };
    const { container } = renderPage();
    await screen.findByText('Weekly product sync');
    await screen.findByText('Vendor call');
    await waitFor(() =>
      expect(screen.getByRole('switch', { name: 'Record my meetings' })).toBeEnabled(),
    );
    expect(stable(container)).toMatchSnapshot();
  });

  it('when the page cannot load', async () => {
    state.fail = true;
    const { container } = renderPage();
    await screen.findByText('Could not reach the calendar.');
    expect(stable(container)).toMatchSnapshot();
  });
});
