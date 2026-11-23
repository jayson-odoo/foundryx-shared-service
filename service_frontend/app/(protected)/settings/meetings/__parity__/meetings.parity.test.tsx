/**
 * Switch-off parity for Settings > Meetings (Foundryx UIUX slice
 * W4-SETTINGS): the page untouched, with a field changed, and as a user who
 * may not change the settings, rendered with the switch OFF. Recorded on the
 * code as it was before the slice; a change that needs one of these snapshots
 * updated is wrong by definition (fix the code, never the snapshot).
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import MeetingsSettingsPage from '../page';

const perms = vi.hoisted(() => ({ manage: true }));

vi.mock('@/services/meetings-service', () => ({
  meetingsService: {
    listBotRuns: vi.fn(async () => [
      {
        id: 'run-1',
        meetingTitle: 'Weekly sales',
        startsAt: '2026-11-18T01:00:00Z',
        startedAt: '2026-11-18T01:01:00Z',
        endedAt: '2026-11-18T01:31:00Z',
        exitReason: null,
        meetingStatus: 'DONE',
        durationS: 1800,
      },
    ]),
    getSettings: vi.fn(async () => ({
      calendarServiceAccountEmail: 'notetaker@proj.iam.gserviceaccount.com',
      minutesLanguage: 'en',
      audioRetentionDays: 90,
      llmConnectionId: null,
      botDisplayName: 'Notetaker',
      consentMessage: null,
    })),
    saveSettings: vi.fn(),
  },
}));
vi.mock('@/services/integration-service', () => ({
  integrationService: { list: async () => ({ data: [], total: 0, page: 0 }) },
}));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/settings/meetings'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { name: 'Demo Admin', permissions: [], timezone: 'UTC' } }, status: 'authenticated' }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({
    can: (p: string) => (p === 'meetings.settings.manage' ? perms.manage : true),
    ready: true,
    permissions: new Set<string>(),
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
      <MeetingsSettingsPage />
    </SettingsProvider>,
  );
}

beforeEach(() => {
  perms.manage = true;
});

describe('parity (switch off): Settings > Meetings', () => {
  it('untouched, then with the display name changed', async () => {
    const { container } = renderPage();
    const name = await screen.findByDisplayValue('Notetaker');
    await screen.findByText('Weekly sales');
    await waitFor(() => expect(name).toBeEnabled());
    expect(stable(container)).toMatchSnapshot();
    fireEvent.change(name, { target: { value: 'Minutes bot' } });
    expect(stable(container)).toMatchSnapshot();
  });

  it('as a user who may not change the settings', async () => {
    perms.manage = false;
    const { container } = renderPage();
    await screen.findByDisplayValue('Notetaker');
    await screen.findByText('Weekly sales');
    expect(stable(container)).toMatchSnapshot();
  });
});
