/**
 * T7 carry-over C1: `MegaMenuSubDefault`/`MegaMenuSubHighlighted` used to call
 * `isActive(item.path)` with no `menuPaths`, so a naive `startsWith` lit up
 * every sibling that shares a prefix - `/developers/logs` and
 * `/developers/logs/settings` both "active" while viewing either one. Passing
 * `collectMenuPaths(visibleMenu)` through (same discipline as the sidebar's
 * AC-DLA-72 fix) restores segment-boundary + most-specific-wins.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { usePathname } from 'next/navigation';
import { MegaMenuSubDefault } from './mega-menu-sub-default';
import { MegaMenuSubHighlighted } from './mega-menu-sub-highlighted';
import { collectMenuPaths } from '@/lib/menu-path-match';
import { NavigationMenu, NavigationMenuList } from '@/components/ui/navigation-menu';
import type { MenuConfig } from '@/config/types';

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(),
}));

const items: MenuConfig = [
  { title: 'Logs', path: '/developers/logs' },
  { title: 'Log settings', path: '/developers/logs/settings' },
];

function Harness({ pathname }: { pathname: string }) {
  vi.mocked(usePathname).mockReturnValue(pathname);
  const menuPaths = collectMenuPaths(items);
  return (
    <NavigationMenu>
      <NavigationMenuList>{MegaMenuSubDefault(items, menuPaths)}</NavigationMenuList>
    </NavigationMenu>
  );
}

function HighlightedHarness({ pathname }: { pathname: string }) {
  vi.mocked(usePathname).mockReturnValue(pathname);
  const menuPaths = collectMenuPaths(items);
  return (
    <NavigationMenu>
      <NavigationMenuList>{MegaMenuSubHighlighted(items, menuPaths)}</NavigationMenuList>
    </NavigationMenu>
  );
}

describe('MegaMenuSubDefault current-item highlight (C1)', () => {
  it('viewing the parent path highlights only the parent, not the child sibling', () => {
    render(<Harness pathname="/developers/logs" />);
    const logsLink = screen.getByRole('link', { name: 'Logs' });
    const settingsLink = screen.getByRole('link', { name: 'Log settings' });
    expect(logsLink).toHaveAttribute('data-active', 'true');
    expect(settingsLink).not.toHaveAttribute('data-active');
  });

  it('viewing the child path highlights only the child', () => {
    render(<Harness pathname="/developers/logs/settings" />);
    const logsLink = screen.getByRole('link', { name: 'Logs' });
    const settingsLink = screen.getByRole('link', { name: 'Log settings' });
    expect(logsLink).not.toHaveAttribute('data-active');
    expect(settingsLink).toHaveAttribute('data-active', 'true');
  });

  it('omitting menuPaths falls back to the old plain-prefix behaviour (documented, not the bug fix)', () => {
    vi.mocked(usePathname).mockReturnValue('/developers/logs');
    render(
      <NavigationMenu>
        <NavigationMenuList>{MegaMenuSubDefault(items)}</NavigationMenuList>
      </NavigationMenu>,
    );
    const logsLink = screen.getByRole('link', { name: 'Logs' });
    expect(logsLink).toHaveAttribute('data-active', 'true');
  });
});

describe('MegaMenuSubHighlighted current-item highlight (C1)', () => {
  it('viewing the parent path highlights only the parent, not the child sibling', () => {
    render(<HighlightedHarness pathname="/developers/logs" />);
    const logsLink = screen.getByRole('link', { name: 'Logs' });
    const settingsLink = screen.getByRole('link', { name: 'Log settings' });
    expect(logsLink).toHaveAttribute('data-active', 'true');
    expect(settingsLink).not.toHaveAttribute('data-active');
  });

  it('viewing the child path highlights only the child', () => {
    render(<HighlightedHarness pathname="/developers/logs/settings" />);
    const logsLink = screen.getByRole('link', { name: 'Logs' });
    const settingsLink = screen.getByRole('link', { name: 'Log settings' });
    expect(logsLink).not.toHaveAttribute('data-active');
    expect(settingsLink).toHaveAttribute('data-active', 'true');
  });
});
