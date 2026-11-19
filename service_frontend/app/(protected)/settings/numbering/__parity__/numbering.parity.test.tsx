/**
 * Switch-off parity for Settings > Numbering (Foundryx UIUX slice
 * W4-SETTINGS): the list, then the edit dialog open with the prefix and next
 * number changed, rendered with the switch OFF. Recorded on the code as it
 * was before the slice; a change that needs one of these snapshots updated is
 * wrong by definition (fix the code, never the snapshot).
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import { NUMBERS_FIXTURE } from '../numbering-fixture.test-data';
import NumberingPage from '../page';

vi.mock('@/lib/api-client', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return {
    ...real,
    apiFetch: vi.fn(async (path: string) => (path === '/numbering' ? NUMBERS_FIXTURE : {})),
  };
});
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/settings/numbering'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { name: 'Demo Admin', permissions: [] } }, status: 'authenticated' }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
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

// The dialog's preview prints today's date.
beforeAll(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-11-19T04:00:00Z'));
});
afterAll(() => vi.useRealTimers());

describe('parity (switch off): Settings > Numbering', () => {
  it('the list, then the edit dialog with a new prefix and next number', async () => {
    const { container } = render(
      <SettingsProvider>
        <NumberingPage />
      </SettingsProvider>,
    );
    await screen.findByText('Q-00007');
    expect(stable(container)).toMatchSnapshot();

    const row = screen.getByText('invoice').closest('tr')!;
    fireEvent.pointerDown(within(row).getByRole('button'), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole('menuitem', { name: /Edit/ }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Prefix'), { target: { value: 'IV/' } });
    fireEvent.change(within(dialog).getByLabelText(/Next value/), { target: { value: '100' } });
    expect(stable(dialog)).toMatchSnapshot();
  });
});
