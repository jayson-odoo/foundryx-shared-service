/**
 * The side rail's logo (switch on) used to point at `/media/app/*.svg`,
 * template files never committed to this repo, so it was a broken image on
 * every page in every environment. It now draws `AppLogo`: the tenant's own
 * favicon/logo, else its name or initial, else (unbranded) the inline
 * wordmark - nothing left to 404.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import type { PublicBranding } from '@/types/branding';
import { FxSidebar } from './fx-sidebar';

vi.mock('next/navigation', () => ({
  usePathname: () => '/user-management/users',
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Alpha Tan', email: 'alpha@example.com', permissions: [] } },
    status: 'authenticated',
  }),
}));
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn(), resolvedTheme: 'light' }),
}));
vi.mock('@/hooks/use-app-store', () => ({
  useInstalledModules: () => ({ ready: true, isActive: () => true }),
}));
vi.mock('@/hooks/use-terminology', () => ({
  useTerminology: () => ({ labelPlural: (k: string) => k, label: (k: string) => k }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/config/menu.config', () => ({
  MENU_SIDEBAR: [{ title: 'Users', path: '/user-management/users' }],
  MENU_MEGA: [],
  MENU_MEGA_MOBILE: [],
}));

const UNBRANDED: PublicBranding = {
  isBranded: false,
  tenantName: null,
  appName: null,
  slogan: null,
  logoUrl: null,
  faviconUrl: null,
  illustrationUrl: null,
  tokens: null,
  version: 0,
};
const brandingRef = vi.hoisted(() => ({ current: null as PublicBranding | null }));
vi.mock('@/hooks/use-branding', () => ({
  useTenantBranding: () => ({ branding: brandingRef.current, isResolved: true }),
}));

function renderRail(branding: PublicBranding) {
  brandingRef.current = branding;
  return render(
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      <FxSidebar />
    </FxProvider>,
  );
}

describe('FxSidebar logo', () => {
  it('unbranded: inline wordmark and initial, no request under /media/app/', () => {
    const { container } = renderRail(UNBRANDED);
    expect(container.innerHTML).not.toContain('/media/app/');
    const home = screen.getByRole('link', { name: 'Home' });
    expect(home.querySelector('img')).toBeNull();
    expect(home.querySelector('svg[aria-label="Foundryx"]')).not.toBeNull();
  });

  it('branded without a logo: the tenant name, never the Foundryx mark', () => {
    const { container } = renderRail({ ...UNBRANDED, isBranded: true, tenantName: 'Acme Co' });
    expect(container.innerHTML).not.toContain('/media/app/');
    expect(container.innerHTML).not.toContain('Foundryx');
    expect(screen.getByText('Acme Co')).toBeInTheDocument();
  });

  it('branded with a logo and favicon: both shown from the tenant', () => {
    renderRail({
      ...UNBRANDED,
      isBranded: true,
      tenantName: 'Acme Co',
      logoUrl: '/branding/acme.png',
      faviconUrl: '/branding/fav.png',
    });
    const srcs = Array.from(
      screen.getByRole('link', { name: 'Home' }).querySelectorAll('img'),
    ).map((img) => img.getAttribute('src'));
    expect(srcs).toEqual(['/branding/fav.png', '/branding/acme.png']);
  });
});
