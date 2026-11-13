'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { SearchDialog } from '@/partials/dialogs/search/search-dialog';
import { AppsDropdownMenu } from '@/partials/topbar/apps-dropdown-menu';
import { ChatSheet } from '@/partials/topbar/chat-sheet';
import { NotificationsSheet } from '@/partials/topbar/notifications-sheet';
import { UserDropdownMenu } from '@/partials/topbar/user-dropdown-menu';
import {
  Bell,
  LayoutGrid,
  Menu,
  MessageCircleMore,
  Search,
  SquareChevronRight,
} from 'lucide-react';
import { useSession } from 'next-auth/react';
import { toAbsoluteUrl } from '@/lib/helpers';
import { cn } from '@/lib/utils';
import { useIsMobile } from '@/hooks/use-mobile';
import { Button } from '@/components/ui/button';
import {
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from '@/components/ui/drawer';
import { Container } from '@/components/common/container';
import { ActivityTriggers } from '@/components/platform/document-drive';
import { UserAvatar } from '@/components/platform/user-avatar';
import { MegaMenu } from './mega-menu';
import { MegaMenuMobile } from './mega-menu-mobile';
import { SidebarMenu } from './sidebar-menu';

export function Header() {
  const [isSidebarSheetOpen, setIsSidebarSheetOpen] = useState(false);
  const [isMegaMenuSheetOpen, setIsMegaMenuSheetOpen] = useState(false);

  const pathname = usePathname();
  const mobileMode = useIsMobile();
  const { data: session } = useSession();

  // Close sheet when route changes
  useEffect(() => {
    setIsSidebarSheetOpen(false);
    setIsMegaMenuSheetOpen(false);
  }, [pathname]);

  return (
    <header className="header material-regular material-edge fixed top-[var(--shell-top-offset,0px)] z-(--z-header) start-0 flex items-stretch shrink-0 border-b border-border end-0 pe-[var(--removed-body-scroll-bar-size,0px)]">
      {/* Fluid like the content pages - the Metronic default was fixed
          max-w-[1320px], which left the header floating centered on wide
          screens while every list page stretches full width (plan 06). */}
      <Container
        width="fluid"
        className="flex justify-between items-stretch lg:gap-4"
      >
        {/* HeaderLogo */}
        <div className="flex gap-1 lg:hidden items-center gap-2.5">
          <Link href="/" className="shrink-0">
            <img
              src={toAbsoluteUrl('/media/app/mini-logo.svg')}
              className="h-[25px] w-[25px] object-contain"
              alt="mini-logo"
            />
          </Link>
          <div className="flex items-center">
            {mobileMode && (
              <Drawer
                open={isSidebarSheetOpen}
                onOpenChange={setIsSidebarSheetOpen}
                direction="left"
                shouldScaleBackground={false}
              >
                <DrawerTrigger asChild>
                  <Button
                    variant="ghost"
                    mode="icon"
                    aria-label="Open navigation"
                  >
                    <Menu className="text-muted-foreground/70" />
                  </Button>
                </DrawerTrigger>
                <DrawerContent className="p-0 gap-0 w-[275px] max-w-[275px]">
                  <DrawerHeader className="p-0 gap-0">
                    <DrawerTitle className="sr-only">Navigation</DrawerTitle>
                  </DrawerHeader>
                  <DrawerBody className="p-0">
                    <SidebarMenu />
                  </DrawerBody>
                </DrawerContent>
              </Drawer>
            )}
            {mobileMode && (
              <Drawer
                open={isMegaMenuSheetOpen}
                onOpenChange={setIsMegaMenuSheetOpen}
                direction="left"
                shouldScaleBackground={false}
              >
                <DrawerTrigger asChild>
                  <Button variant="ghost" mode="icon" aria-label="Open apps menu">
                    <SquareChevronRight className="text-muted-foreground/70" />
                  </Button>
                </DrawerTrigger>
                <DrawerContent className="p-0 gap-0 w-[275px] max-w-[275px]">
                  <DrawerHeader className="p-0 gap-0">
                    <DrawerTitle className="sr-only">Apps</DrawerTitle>
                  </DrawerHeader>
                  <DrawerBody className="p-0">
                    <MegaMenuMobile />
                  </DrawerBody>
                </DrawerContent>
              </Drawer>
            )}
          </div>
        </div>

        {/* Main Content - the mega menu renders on every page. (The old
            Metronic special-case swapped in <Breadcrumb /> for /account demo
            pages, which left the real My Account page with an empty header.) */}
        {!mobileMode && <MegaMenu />}

        {/* HeaderTopbar - gap tightens on mobile (T7 fix round 1) so the
            Uploads/Downloads triggers fit alongside Notifications/Chat/Apps/
            the avatar without overlap at 375px. */}
        <div className={cn('flex items-center', mobileMode ? 'gap-1' : 'gap-3')}>
          {
            <>
              {!mobileMode && (
                <SearchDialog
                  trigger={
                    <Button
                      variant="ghost"
                      mode="icon"
                      shape="circle"
                      aria-label="Search"
                      className="size-9 hover:bg-primary/10 hover:[&_svg]:text-primary"
                    >
                      <Search className="size-4.5!" />
                    </Button>
                  }
                />
              )}
              {/* T7 (AC-DLA-62): all 4 icons (Uploads/Imports/Jobs/Downloads)
                  with no wrap/shrink protection overflowed the 375px header
                  and visually overlapped the hamburger + apps-menu drawer
                  triggers on the left. Fix round 1: rather than hiding the
                  whole group on mobile (which silently dropped the Uploads/
                  Downloads drawers entirely), only Uploads + Downloads
                  render on mobile - Imports/Jobs stay reachable via the
                  sidebar drawer's own menu entries, where header width is
                  tight. `compact` (mobile only) drops the invisible
                  44px coarse-pointer touch pad (`COARSE_HIT_TARGET_CLASS`) -
                  same visible size, but this is now a dense cluster (6 icons
                  in a 375px header) where overlapping touch pads is the
                  documented reason NOT to carry that class. */}
              <ActivityTriggers
                only={mobileMode ? ['uploads', 'downloads'] : undefined}
                compact={mobileMode}
              />
              <NotificationsSheet
                trigger={
                  <Button
                    variant="ghost"
                    mode="icon"
                    size={mobileMode ? 'sm' : undefined}
                    shape="circle"
                    aria-label="Notifications"
                    className="size-9 hover:bg-primary/10 hover:[&_svg]:text-primary"
                  >
                    <Bell className="size-4.5!" />
                  </Button>
                }
              />
              <ChatSheet
                trigger={
                  <Button
                    variant="ghost"
                    mode="icon"
                    size={mobileMode ? 'sm' : undefined}
                    shape="circle"
                    aria-label="Chat"
                    className="size-9 hover:bg-primary/10 hover:[&_svg]:text-primary"
                  >
                    <MessageCircleMore className="size-4.5!" />
                  </Button>
                }
              />
              <AppsDropdownMenu
                trigger={
                  <Button
                    variant="ghost"
                    mode="icon"
                    size={mobileMode ? 'sm' : undefined}
                    shape="circle"
                    aria-label="Apps"
                    className="size-9 hover:bg-primary/10 hover:[&_svg]:text-primary"
                  >
                    <LayoutGrid className="size-4.5!" />
                  </Button>
                }
              />
              <UserDropdownMenu
                trigger={
                  // Real session avatar (initials fallback) - the Metronic
                  // demo image is gone (plan 06 D5).
                  <button
                    type="button"
                    aria-label="User menu"
                    className="shrink-0 cursor-pointer rounded-full"
                  >
                    <UserAvatar
                      user={{
                        name: session?.user.name ?? null,
                        email: session?.user.email ?? '',
                        avatar: session?.user.avatar ?? null,
                      }}
                      size="md"
                      className="border-2 border-green-500"
                    />
                  </button>
                }
              />
            </>
          }
        </div>
      </Container>
    </header>
  );
}
