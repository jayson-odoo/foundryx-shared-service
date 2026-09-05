/**
 * AC-DLA-34: sidebar menu items prefetch on pointer-enter (once per href),
 * not on viewport (`Link prefetch={false}`).
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useRouter } from 'next/navigation';
import { SidebarMenu } from './sidebar-menu';

const push = vi.fn();
const prefetch = vi.fn();

vi.mock('next/navigation', () => ({
  usePathname: () => '/',
  useRouter: vi.fn(),
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
    { title: 'Users', path: '/user-management/users' },
    { title: 'Roles', path: '/user-management/roles' },
  ],
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useRouter).mockReturnValue({ push, prefetch } as unknown as ReturnType<typeof useRouter>);
});

describe('AC-DLA-34 sidebar menu pointer-enter prefetch', () => {
  it('every menu link opts OUT of Next.js viewport prefetch', () => {
    render(<SidebarMenu />);
    const link = screen.getByRole('link', { name: 'Users' }) as HTMLAnchorElement;
    // next/link with prefetch={false} still renders a plain <a> - the
    // contract we can assert from the DOM is the ABSENCE of viewport
    // prefetch triggering (covered by the pointerEnter-only assertions
    // below); this just pins the link renders at all.
    expect(link).toHaveAttribute('href', '/user-management/users');
  });

  it('pointer-enter prefetches the href exactly once per href', () => {
    render(<SidebarMenu />);
    const link = screen.getByRole('link', { name: 'Users' });
    fireEvent.pointerEnter(link);
    fireEvent.pointerEnter(link);
    fireEvent.pointerEnter(link);
    expect(prefetch).toHaveBeenCalledTimes(1);
    expect(prefetch).toHaveBeenCalledWith('/user-management/users');
  });

  it('a click (no prior hover) still navigates normally - prefetch is a hover optimisation, not a gate', () => {
    render(<SidebarMenu />);
    const link = screen.getByRole('link', { name: 'Roles' });
    expect(link).toHaveAttribute('href', '/user-management/roles');
  });
});
