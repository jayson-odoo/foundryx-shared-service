/**
 * Switch-off parity for Settings > General (Foundryx UIUX slice W4-SETTINGS):
 * the page untouched, with a value changed, and as a view-only user, rendered
 * with the switch OFF. Recorded on the code as it was before the slice; a
 * change that needs one of these snapshots updated is wrong by definition
 * (fix the code, never the snapshot).
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import GeneralSettingsPage from '../page';

const perms = vi.hoisted(() => ({ manage: true }));

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/settings/general'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { name: 'Demo Admin', permissions: [] } }, status: 'authenticated' }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({
    can: (p: string) => (p === 'settings.update' ? perms.manage : true),
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
vi.mock('@/services/ems-service', () => ({
  emsService: {
    getTenantSettings: vi.fn(async () => ({
      defaultCurrency: 'MYR',
      priceDecimals: 2,
      deferredDestructiveSeconds: 10,
      deferredReversibleSeconds: 5,
    })),
    setTenantSettings: vi.fn(),
  },
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
      <GeneralSettingsPage />
    </SettingsProvider>,
  );
}

beforeEach(() => {
  perms.manage = true;
});

describe('parity (switch off): Settings > General', () => {
  it('untouched, then with the decimals and a countdown changed', async () => {
    const { container } = renderPage();
    const decimals = await screen.findByDisplayValue('2');
    await screen.findByDisplayValue('10');
    expect(stable(container)).toMatchSnapshot();
    fireEvent.change(decimals, { target: { value: '3' } });
    fireEvent.change(screen.getByDisplayValue('10'), { target: { value: '12' } });
    expect(stable(container)).toMatchSnapshot();
  });

  it('as a user who may read but not change the settings', async () => {
    perms.manage = false;
    const { container } = renderPage();
    await screen.findByDisplayValue('2');
    await screen.findByDisplayValue('10');
    expect(stable(container)).toMatchSnapshot();
  });
});
