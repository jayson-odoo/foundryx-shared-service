/**
 * Settings > Meetings with the Foundryx UIUX switch on (slice W4-SETTINGS):
 * the red action "Save meeting settings" sends exactly what today's button
 * sends for the same input; a user who may not change the settings sees
 * plain text; Undo writes the earlier settings back. Switch off is pinned by
 * `__parity__/meetings.parity.test.tsx`.
 */
import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingsSettings } from '@/types/meetings';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import MeetingsSettingsPage from './page';

const STORED: MeetingsSettings = {
  calendarServiceAccountEmail: 'notetaker@proj.iam.gserviceaccount.com',
  minutesLanguage: 'ms',
  audioRetentionDays: 30,
  llmConnectionId: null,
  botDisplayName: 'Notetaker',
  consentMessage: 'Recorded.',
};
const saveSettings = vi.hoisted(() => vi.fn());
const perms = vi.hoisted(() => ({ manage: true }));

vi.mock('@/services/meetings-service', () => ({
  meetingsService: {
    listBotRuns: vi.fn(async () => []),
    getSettings: vi.fn(async () => STORED),
    saveSettings: (input: unknown) => saveSettings(input),
  },
}));
vi.mock('@/services/integration-service', () => ({
  integrationService: { list: async () => ({ data: [], total: 0, page: 0 }) },
}));
const toasts = vi.hoisted(() => ({ fxDone: vi.fn(), error: vi.fn(), success: vi.fn() }));
vi.mock('@/lib/toast', async (orig) => {
  const real = (await orig()) as { toast: Record<string, unknown> };
  return { toast: { ...real.toast, ...toasts } };
});
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({
    can: (p: string) => (p === 'meetings.settings.manage' ? perms.manage : true),
    ready: true,
    permissions: new Set<string>(),
  }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: ReactNode }) => children,
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
vi.mock('next-themes', () => ({ useTheme: () => ({ theme: 'light', setTheme: vi.fn() }) }));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/settings/meetings'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Nurul Huda', permissions: [], timezone: 'UTC' } },
    status: 'authenticated',
  }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
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

beforeEach(() => {
  perms.manage = true;
  saveSettings.mockReset();
  saveSettings.mockImplementation(async (input: Partial<MeetingsSettings>) => ({ ...STORED, ...input }));
  Object.values(toasts).forEach((fn) => fn.mockReset());
});
afterEach(() => resetPageActionsForTests());

async function saveIn(on: boolean, name: string, consent: string) {
  const view = render(<MeetingsSettingsPage />, { wrapper: look(on) });
  const field = await screen.findByLabelText('Notetaker display name');
  await waitFor(() => expect(field).toBeEnabled());
  await screen.findByDisplayValue('Notetaker');
  fireEvent.change(field, { target: { value: name } });
  fireEvent.change(screen.getByLabelText('Consent message'), { target: { value: consent } });
  fireEvent.click(screen.getByRole('button', { name: 'Save meeting settings' }));
  await waitFor(() => expect(saveSettings).toHaveBeenCalledTimes(1));
  return view;
}

describe('the same save in both looks', () => {
  it.each([
    ['a new name and message', '  Minutes bot ', 'We record this call.'],
    ['blanks (sent as null)', '   ', ''],
    ['unchanged', 'Notetaker', 'Recorded.'],
  ])('%s', async (_n, name, consent) => {
    (await saveIn(false, name, consent)).unmount();
    const off = saveSettings.mock.calls[0][0];
    saveSettings.mockClear();
    resetPageActionsForTests();
    await saveIn(true, name, consent);
    expect(saveSettings.mock.calls[0][0]).toEqual(off);
  });
});

describe('done toast and Undo', () => {
  it('Undo writes the earlier settings back', async () => {
    await saveIn(true, 'Minutes bot', '');
    await waitFor(() => expect(toasts.fxDone).toHaveBeenCalled());
    const done = toasts.fxDone.mock.calls[0][0];
    expect(done).toMatchObject({ what: 'Meeting settings saved', byWhom: 'Nurul Huda' });
    saveSettings.mockClear();
    done.undo();
    await waitFor(() => expect(saveSettings).toHaveBeenCalledTimes(1));
    expect(saveSettings.mock.calls[0][0]).toEqual({
      minutesLanguage: 'ms',
      audioRetentionDays: 30,
      botDisplayName: 'Notetaker',
      consentMessage: 'Recorded.',
    });
  });
});

describe('view-only', () => {
  it('shows plain text and no red action', async () => {
    perms.manage = false;
    render(<MeetingsSettingsPage />, { wrapper: look(true) });
    expect(await screen.findByText('Malay')).toBeInTheDocument();
    expect(screen.getByText('30 days')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save meeting settings' })).toBeNull();
    expect(screen.queryByLabelText('Notetaker display name')).toBeNull();
  });
});
