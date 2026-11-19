/**
 * Switch-off parity for Settings > Imports (Foundryx UIUX slice
 * W4-SETTINGS): the page untouched and with the row cap changed, rendered
 * with the switch OFF. Recorded on the code as it was before the slice; a
 * change that needs one of these snapshots updated is wrong by definition
 * (fix the code, never the snapshot).
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import ImportSettingsPage from '../page';

vi.mock('@/lib/api-client', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return {
    ...real,
    apiFetch: vi.fn(async (path: string) =>
      path === '/imports/settings' ? { maxRows: 50000, maxFileMb: 25, isDefault: false } : {},
    ),
  };
});
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/settings/imports'),
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

describe('parity (switch off): Settings > Imports', () => {
  it('untouched, then with the row cap changed', async () => {
    const { container } = render(
      <SettingsProvider>
        <ImportSettingsPage />
      </SettingsProvider>,
    );
    const rows = await screen.findByDisplayValue('50000');
    await screen.findByDisplayValue('25');
    expect(stable(container)).toMatchSnapshot();
    fireEvent.change(rows, { target: { value: '1000' } });
    expect(stable(container)).toMatchSnapshot();
  });
});
