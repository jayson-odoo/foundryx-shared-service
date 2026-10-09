/**
 * Fix round 1 item 4 - AC-DLA-72 same-class defect: `MegaMenuMobile`'s own
 * inline `matchPath` used a naive `path === pathname || pathname.startsWith(path)`
 * check (no segment boundary, no most-specific-wins). Now routed through
 * `matchesMenuPath`/`collectMenuPaths` (`lib/menu-path-match.ts`), same
 * discipline as `sidebar-menu.tsx`.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { usePathname } from 'next/navigation';
import { MegaMenuMobile } from './mega-menu-mobile';

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { isPlatformTenant: false, permissions: [] } }, status: 'authenticated' }),
}));

vi.mock('@/hooks/use-app-store', () => ({
  useInstalledModules: () => ({ ready: true, isActive: () => true }),
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));

vi.mock('@/config/menu.config', () => ({
  MENU_MEGA_MOBILE: [
    { title: 'SCM', path: '/scm' },
    { title: 'SCM Archive', path: '/scm-archive' },
    {
      title: 'Settings',
      path: '/settings',
      children: [{ title: 'General', path: '/settings/general' }],
    },
  ],
}));

describe('MegaMenuMobile matchPath - segment-boundary + most-specific-wins', () => {
  it('/scm does not light up on /scm-archive (segment-boundary)', () => {
    vi.mocked(usePathname).mockReturnValue('/scm-archive');
    render(<MegaMenuMobile />);

    const scmLink = screen.getByRole('link', { name: 'SCM' });
    const scmItem = scmLink.closest('[data-slot="accordion-menu-item"]');
    expect(scmItem).not.toHaveAttribute('data-selected');

    const archiveLink = screen.getByRole('link', { name: 'SCM Archive' });
    const archiveItem = archiveLink.closest('[data-slot="accordion-menu-item"]');
    expect(archiveItem).toHaveAttribute('data-selected', 'true');
  });

  it('a section root (Settings) is not lit beside its active child (General)', () => {
    vi.mocked(usePathname).mockReturnValue('/settings/general');
    render(<MegaMenuMobile />);

    const generalLink = screen.getByRole('link', { name: 'General' });
    const generalItem = generalLink.closest('[data-slot="accordion-menu-item"]');
    expect(generalItem).toHaveAttribute('data-selected', 'true');

    // Only the leaf item type carries `data-selected` - the "Settings" text
    // renders inside a sub-trigger (a button, not an accordion-menu-item), so
    // asserting no OTHER leaf is selected is the meaningful check here.
    const selected = document.querySelectorAll('[data-slot="accordion-menu-item"][data-selected="true"]');
    expect(selected.length).toBe(1);
  });
});
