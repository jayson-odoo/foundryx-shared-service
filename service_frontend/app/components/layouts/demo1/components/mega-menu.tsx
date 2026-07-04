'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
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
import { MegaMenuSubDefault } from '@/app/components/partials/mega-menu/components';

// MegaMenuSubDefault calls hooks (usePathname/useMenu) internally, so it MUST be
// rendered as its own component/fiber — calling it positionally inside .map()
// would run its hooks in MegaMenu's fiber a variable number of times (the count
// shifts as filterMenu resolves), tripping Rules-of-Hooks and white-screening.
function MegaMenuSection({ items }: { items: MenuItem[] }) {
  return <>{MegaMenuSubDefault(items)}</>;
}

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

  const linkClass = `
    text-sm text-secondary-foreground font-medium
    hover:text-primary hover:bg-transparent
    focus:text-primary focus:bg-transparent
    data-[active=true]:text-primary data-[active=true]:bg-transparent
    data-[state=open]:text-primary data-[state=open]:bg-transparent
  `;

  // Render GENERICALLY from the (permission/module-filtered) menu — resolve
  // sections by existence, never by fixed index. The EMS/portal sections this
  // header used to hardcode (Public Profiles, Network) were stripped in the
  // shared-service fork, so any fixed-index dereference would crash the page.
  return (
    <NavigationMenu>
      <NavigationMenuList className="gap-0">
        {visibleMenu.map((item, index) => {
          if (item.heading) return null;
          const label = menuLabel(item);
          const children = item.children;

          if (children && children.length > 0) {
            return (
              <NavigationMenuItem key={item.path || `mega-${index}`}>
                <NavigationMenuTrigger
                  className={cn(linkClass)}
                  data-active={hasActiveChild(children) || undefined}
                >
                  {label}
                </NavigationMenuTrigger>
                <NavigationMenuContent className="p-0">
                  <div className="w-full space-y-0.5 p-4 lg:w-[320px] lg:p-5">
                    <MegaMenuSection items={children} />
                  </div>
                </NavigationMenuContent>
              </NavigationMenuItem>
            );
          }

          if (!item.path) return null;
          return (
            <NavigationMenuItem key={item.path || `mega-${index}`}>
              <NavigationMenuLink asChild>
                <Link
                  href={item.path}
                  className={cn(linkClass)}
                  data-active={isActive(item.path) || undefined}
                >
                  {label}
                </Link>
              </NavigationMenuLink>
            </NavigationMenuItem>
          );
        })}
      </NavigationMenuList>
    </NavigationMenu>
  );
}
