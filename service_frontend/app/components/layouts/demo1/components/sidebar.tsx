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
        'sidebar material-thick lg:border-e lg:border-border lg:fixed lg:top-[var(--impersonation-banner-height,0px)] lg:bottom-0 lg:z-(--z-sidebar) lg:flex flex-col items-stretch shrink-0',
        (settings.layouts.demo1.sidebarTheme === 'dark' ||
          pathname.includes('dark-sidebar')) &&
          'dark',
      )}
    >
      <SidebarHeader />
      <div className="overflow-hidden">
        <div className="w-(--sidebar-default-width)">
          <SidebarMenu />
        </div>
      </div>
    </div>
  );
}
