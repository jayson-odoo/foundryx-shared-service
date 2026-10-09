'use client';

import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { useSettings } from '@/providers/settings-provider';
import { SidebarHeader } from './sidebar-header';
import { SidebarMenu } from './sidebar-menu';

export function Sidebar() {
  const { settings } = useSettings();
  const pathname = usePathname();

  return (
    <div
      className={cn(
        'sidebar material-thick lg:border-e lg:border-border lg:fixed lg:top-[var(--shell-top-offset,0px)] lg:bottom-0 lg:z-(--z-sidebar) lg:flex flex-col items-stretch shrink-0',
        (settings.layouts.demo1.sidebarTheme === 'dark' ||
          pathname.includes('dark-sidebar')) &&
          'dark',
      )}
    >
      <SidebarHeader />
      {/* flex-1 min-h-0: bounds this wrapper to whatever height remains below
          SidebarHeader inside the fixed sidebar box (itself lg:top-(--shell-top-offset)
          lg:bottom-0, so its own height already shrinks when the impersonation banner
          is expanded) - without min-h-0 a flex child never shrinks below its content
          size, so this stayed content-sized and the menu's own 100vh-based cap (fixed
          in sidebar-menu.tsx) overflowed past the sidebar's real bottom edge. */}
      <div className="overflow-hidden flex-1 min-h-0">
        <div className="w-(--sidebar-default-width) h-full">
          <SidebarMenu />
        </div>
      </div>
    </div>
  );
}
