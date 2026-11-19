/**
 * Switch-off parity for Settings > Terminology (Foundryx UIUX slice
 * W4-SETTINGS): the list, then the rename dialog open with a label typed,
 * rendered with the switch OFF. Recorded on the code as it was before the
 * slice; a change that needs one of these snapshots updated is wrong by
 * definition (fix the code, never the snapshot).
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import { TERMS_FIXTURE } from '../terminology-fixture.test-data';
import TerminologyPage from '../page';

vi.mock('@/lib/api-client', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return {
    ...real,
    apiFetch: vi.fn(async (path: string) => (path === '/terminology/catalog' ? TERMS_FIXTURE : {})),
  };
});
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/settings/terminology'),
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

describe('parity (switch off): Settings > Terminology', () => {
  it('the list, then the rename dialog with a label typed', async () => {
    const { container } = render(
      <SettingsProvider>
        <TerminologyPage />
      </SettingsProvider>,
    );
    await screen.findByText('Item / Items');
    expect(stable(container)).toMatchSnapshot();

    const row = screen.getByText('contact').closest('tr')!;
    fireEvent.pointerDown(within(row).getByRole('button'), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole('menuitem', { name: /Edit/ }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/Singular/), { target: { value: 'Customer' } });
    expect(stable(dialog)).toMatchSnapshot();
  });
});
