/**
 * AC-DLA-72: sidebar items press like every other control (`PRESSED_CLASS`
 * on both `classNames.item` and `classNames.subTrigger`), and "current" is
 * decided by `lib/menu-path-match.ts` (segment-boundary + most-specific-
 * wins against the VISIBLE menu) - a section root never stays lit beside
 * its active child.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { usePathname } from 'next/navigation';
import { SidebarMenu } from './sidebar-menu';

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(),
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn() }),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { isPlatformTenant: false, permissions: [] } }, status: 'authenticated' }),
}));

vi.mock('@/hooks/use-app-store', () => ({
  useInstalledModules: () => ({ ready: true, isActive: () => true }),
}));

vi.mock('@/hooks/use-terminology', () => ({
  useTerminology: () => ({ labelPlural: (k: string) => k }),
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));

vi.mock('@/config/menu.config', () => ({
  MENU_SIDEBAR: [
    { title: 'Dashboard', path: '/' },
    {
      title: 'User Management',
      children: [
        { title: 'Users', path: '/user-management/users' },
        { title: 'Roles', path: '/user-management/roles' },
      ],
    },
  ],
}));

describe('AC-DLA-72 sidebar item pressed feedback', () => {
  it('a leaf item carries the PRESSED_CLASS active:scale + duration-fast tokens', () => {
    vi.mocked(usePathname).mockReturnValue('/');
    render(<SidebarMenu />);
    const link = screen.getByRole('link', { name: 'Dashboard' });
    const item = link.closest('[data-slot="accordion-menu-item"]') ?? link.parentElement;
    expect(item?.className).toContain('active:scale-[0.97]');
    expect(item?.className).toContain('motion-reduce:active:scale-100');
    expect(item?.className).toContain('duration-(--duration-fast)');
  });

  it('a group sub-trigger (User Management) carries the same PRESSED_CLASS tokens', () => {
    vi.mocked(usePathname).mockReturnValue('/');
    render(<SidebarMenu />);
    const trigger = screen.getByText('User Management').closest('button');
    expect(trigger?.className).toContain('active:scale-[0.97]');
    expect(trigger?.className).toContain('duration-(--duration-fast)');
  });

  it('items no longer carry the hover:bg-transparent override', () => {
    vi.mocked(usePathname).mockReturnValue('/');
    render(<SidebarMenu />);
    const link = screen.getByRole('link', { name: 'Dashboard' });
    const item = link.closest('[data-slot="accordion-menu-item"]') ?? link.parentElement;
    expect(item?.className).not.toContain('hover:bg-transparent');
  });
});

describe('AC-DLA-72 "current" = segment-boundary + most-specific-wins', () => {
  // `AccordionMenuItem` only renders `data-selected` when it IS selected
  // (the primitive sets `undefined` otherwise, which React drops from the
  // DOM entirely - a NOT-selected leaf carries no attribute at all).
  it('on a child page (Users), exactly the Users item is selected - the sibling Roles item is not', () => {
    vi.mocked(usePathname).mockReturnValue('/user-management/users');
    render(<SidebarMenu />);

    const usersLink = screen.getByRole('link', { name: 'Users' });
    const usersItem = usersLink.closest('[data-slot="accordion-menu-item"]');
    expect(usersItem).toHaveAttribute('data-selected', 'true');

    const rolesLink = screen.getByRole('link', { name: 'Roles' });
    const rolesItem = rolesLink.closest('[data-slot="accordion-menu-item"]');
    expect(rolesItem).not.toHaveAttribute('data-selected');
  });

  it('the root Dashboard entry never lights up on a User Management sub-page', () => {
    vi.mocked(usePathname).mockReturnValue('/user-management/users');
    render(<SidebarMenu />);
    const dashboardLink = screen.getByRole('link', { name: 'Dashboard' });
    const dashboardItem = dashboardLink.closest('[data-slot="accordion-menu-item"]');
    expect(dashboardItem).not.toHaveAttribute('data-selected');
  });

  it('exactly one leaf item is selected on a user record page', () => {
    vi.mocked(usePathname).mockReturnValue('/user-management/users');
    render(<SidebarMenu />);
    const selected = document.querySelectorAll('[data-slot="accordion-menu-item"][data-selected="true"]');
    expect(selected.length).toBe(1);
  });
});
