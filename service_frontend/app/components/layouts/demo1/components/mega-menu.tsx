'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { MegaMenuSubAccount } from '@/partials/mega-menu/mega-menu-sub-account';
import { MegaMenuSubNetwork } from '@/partials/mega-menu/mega-menu-sub-network';
import { MegaMenuSubProfiles } from '@/partials/mega-menu/mega-menu-sub-profiles';
import { useMemo } from 'react';
import { useSession } from 'next-auth/react';
import { MENU_MEGA } from '@/config/menu.config';
import { filterMenu } from '@/lib/menu-filter';
import { cn } from '@/lib/utils';
import { useCan } from '@/hooks/use-can';
import { useInstalledModules } from '@/hooks/use-app-store';
import { useMenu } from '@/hooks/use-menu';
import { useTerminology } from '@/hooks/use-terminology';
import type { MenuItem } from '@/config/types';
import {
  NavigationMenu,
  NavigationMenuContent,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
  NavigationMenuTrigger,
} from '@/components/ui/navigation-menu';
import { MegaMenuSubApps } from '@/app/components/partials/mega-menu/mega-menu-sub-apps';

export function MegaMenu() {
  const pathname = usePathname();
  const { isActive, hasActiveChild } = useMenu(pathname);
  const { data: session } = useSession();
  const { can } = useCan();
  const installed = useInstalledModules();
  const { labelPlural } = useTerminology();
  // Relabelable entries (F10) resolve their plural via terminology; title is
  // the never-blank fallback.
  const menuLabel = (item: MenuItem): string | undefined =>
    item.termKey ? labelPlural(item.termKey) : item.title;
  const showPlatform =
    session?.user?.isPlatformTenant === true && can('tenants.read');
  // Same visibility pass as the sidebar (BL-014) — gated entries must not
  // resurface through the header mega menu.
  const visibleMenu = useMemo(
    () =>
      filterMenu(MENU_MEGA, {
        can,
        isModuleActive: installed.isActive,
        modulesReady: installed.ready,
        showPlatform,
      }),
    [can, installed.isActive, installed.ready, showPlatform],
  );
  const homeItem = visibleMenu[0];
  const publicProfilesItem = visibleMenu[1];
  const myAccountItem = visibleMenu[2];
  const networkItem = visibleMenu[3];
  const appsStore = visibleMenu[4];

  const linkClass = `
    text-sm text-secondary-foreground font-medium 
    hover:text-primary hover:bg-transparent 
    focus:text-primary focus:bg-transparent 
    data-[active=true]:text-primary data-[active=true]:bg-transparent 
    data-[state=open]:text-primary data-[state=open]:bg-transparent
  `;

  return (
    <NavigationMenu>
      <NavigationMenuList className="gap-0">
        {/* Home Item */}
        <NavigationMenuItem>
          <NavigationMenuLink asChild>
            <Link
              href={homeItem.path || '/'}
              className={cn(linkClass)}
              data-active={isActive(homeItem.path) || undefined}
            >
              {menuLabel(homeItem)}
            </Link>
          </NavigationMenuLink>
        </NavigationMenuItem>

        {/* Public Profiles Item */}
        <NavigationMenuItem>
          <NavigationMenuTrigger
            className={cn(linkClass)}
            data-active={
              hasActiveChild(publicProfilesItem.children) || undefined
            }
          >
            {menuLabel(publicProfilesItem)}
          </NavigationMenuTrigger>
          <NavigationMenuContent className="p-0">
            <MegaMenuSubProfiles items={visibleMenu} />
          </NavigationMenuContent>
        </NavigationMenuItem>

        {/* My Account Item */}
        <NavigationMenuItem>
          <NavigationMenuTrigger
            className={cn(linkClass)}
            data-active={hasActiveChild(myAccountItem.children) || undefined}
          >
            {menuLabel(myAccountItem)}
          </NavigationMenuTrigger>
          <NavigationMenuContent className="p-0">
            <MegaMenuSubAccount items={visibleMenu} />
          </NavigationMenuContent>
        </NavigationMenuItem>

        {/* Network Item */}
        <NavigationMenuItem>
          <NavigationMenuTrigger
            className={cn(linkClass)}
            data-active={
              hasActiveChild(networkItem.children || []) || undefined
            }
          >
            {menuLabel(networkItem)}
          </NavigationMenuTrigger>
          <NavigationMenuContent className="p-0">
            <MegaMenuSubNetwork items={visibleMenu} />
          </NavigationMenuContent>
        </NavigationMenuItem>

        {/* Apps Item */}
        <NavigationMenuItem>
          <NavigationMenuTrigger
            className={cn(linkClass)}
            data-active={hasActiveChild(appsStore.children || []) || undefined}
          >
            {menuLabel(appsStore)}
          </NavigationMenuTrigger>
          <NavigationMenuContent className="p-0">
            <MegaMenuSubApps items={visibleMenu} />
          </NavigationMenuContent>
        </NavigationMenuItem>
      </NavigationMenuList>
    </NavigationMenu>
  );
}
