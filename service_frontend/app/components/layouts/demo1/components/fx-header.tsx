'use client';

/**
 * The Foundryx UIUX top bar (playbook 0.71.0 "Navigation and panels"),
 * selected by `header.tsx` only while the switch is on.
 *
 * - Icon-only buttons with tooltips. One Jobs button (badge: the work still
 *   running) replaces Uploads, Imports, Jobs and Downloads and opens one
 *   sheet with the four lists as tabs (owner choice: one Jobs place).
 *   Notifications, Chat, Apps and the Theme button stay; the mega menu stays,
 *   so no way to a page is lost.
 * - Above it, the system banner bar.
 * - Wider screens: once the page scrolls about 64px it slides up and out
 *   (0.35 s) and its search box moves into the frozen page header (the same
 *   control moved, not a copy); under 24px it comes back. Setting "Merge
 *   into the page header on scroll".
 * - Phones (720px and narrower): it stays frozen while the page header
 *   scrolls away under it; once the page's red button has gone under it, it
 *   condenses (its icon buttons fold into one menu button, search narrows to
 *   36px high) and a copy of the red button floats in at the lower right.
 *   Settings "Condense the top bar on scroll" and "Floating red action".
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { usePathname } from 'next/navigation';
import { SearchDialog } from '@/partials/dialogs/search/search-dialog';
import { AppsDropdownMenu } from '@/partials/topbar/apps-dropdown-menu';
import { ChatSheet } from '@/partials/topbar/chat-sheet';
import { NotificationsSheet } from '@/partials/topbar/notifications-sheet';
import { UserDropdownMenu } from '@/partials/topbar/user-dropdown-menu';
import { SquareChevronRight } from 'lucide-react';
import { useSession } from 'next-auth/react';
import { cn } from '@/lib/utils';
import { useFxSetting } from '@/hooks/use-fx';
import { useIsMobile } from '@/hooks/use-mobile';
import { useMediaQuery } from '@/hooks/use-media-query';
import { Button } from '@/components/ui/button';
import {
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from '@/components/ui/drawer';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { FxMainAction } from '@/components/fx/actions/main-action';
import { usePageActions } from '@/components/fx/actions/page-actions-context';
import { FxIconActionButton } from '@/components/fx/actions/icon-action';
import { FxTooltip } from '@/components/fx/fx-tooltip';
import { FxIcon } from '@/components/fx/icons';
import { FxSystemBannerHost } from '@/components/fx/banners/system-banner';
import { FxJobsSheet, useJobsPlace } from '@/components/fx/shell/jobs-sheet';
import {
  FX_PHONE_MAX,
  nextCondensed,
  nextMerged,
} from '@/components/fx/shell/scroll-rules';
import { ThemeButton } from '@/components/fx/theme/theme-button';
import { UserAvatar } from '@/components/platform/user-avatar';
import { MegaMenu } from './mega-menu';
import { MegaMenuMobile } from './mega-menu-mobile';
import { FxSideMenu } from './fx-sidebar';

const PHONE_QUERY = `(max-width: ${FX_PHONE_MAX}px)`;

/** An icon button of the bar, with its tooltip. The wrapper takes the tooltip
 *  so the sheet and menu triggers keep their own `asChild` button. */
function BarTip({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <FxTooltip label={label}>
      <span className="inline-flex">{children}</span>
    </FxTooltip>
  );
}

function JobsButton() {
  const place = useJobsPlace();
  const label =
    place.total > 0 ? `Jobs, ${place.total} running` : 'Jobs';
  return (
    <BarTip label="Jobs">
      <span className="relative inline-flex">
        <FxIconActionButton
          mini
          label={label}
          icon="jobs"
          onClick={() => place.open()}
        />
        {place.total > 0 && (
          <span
            aria-hidden="true"
            className="pointer-events-none absolute -end-1 -top-1 flex min-w-4 items-center justify-center rounded-(--fx-r-pill) bg-(--fx-act) px-1 text-2xs font-semibold text-(--fx-act-ink) tabular-nums"
          >
            {place.total}
          </span>
        )}
      </span>
    </BarTip>
  );
}

/** The bar's icon buttons (everything right of search). */
function BarTools({ phone }: { phone: boolean }) {
  const { data: session } = useSession();
  return (
    <>
      <JobsButton />
      {!phone && <ThemeButton />}
      <BarTip label="Notifications">
        <NotificationsSheet
          trigger={<FxIconActionButton mini label="Notifications" icon="notifications" />}
        />
      </BarTip>
      <BarTip label="Chat">
        <ChatSheet trigger={<FxIconActionButton mini label="Chat" icon="chat" />} />
      </BarTip>
      <BarTip label="Apps">
        <AppsDropdownMenu
          trigger={<FxIconActionButton mini label="Apps" icon="apps" />}
        />
      </BarTip>
      <UserDropdownMenu
        trigger={
          <button
            type="button"
            aria-label="User menu"
            className={cn(PRESSED_CLASS, 'shrink-0 cursor-pointer rounded-full')}
          >
            <UserAvatar
              user={{
                name: session?.user.name ?? null,
                email: session?.user.email ?? '',
                avatar: session?.user.avatar ?? null,
              }}
              size="md"
            />
          </button>
        }
      />
    </>
  );
}

/** The red action's floating copy on a phone once the header has scrolled
 *  away. Blocked, tapping it pulses what it waits for (FxMainAction). */
function FloatingMainAction() {
  const page = usePageActions();
  const main = page.hidden ? null : page.main;
  if (!main) return null;
  return (
    <div
      data-fx-floating-action=""
      className="fixed bottom-4 end-4 z-(--fx-z-pop) duration-(--fx-t-layout) ease-(--fx-ease-out) animate-in fade-in-0 slide-in-from-bottom-2"
    >
      <FxMainAction
        key={main.id}
        label={main.label}
        fullLabel={main.fullLabel}
        onClick={main.onClick}
        form={main.form}
        type={main.form ? 'submit' : 'button'}
        blocked={main.blocked}
        working={main.working}
      />
    </div>
  );
}

export function FxHeader() {
  const pathname = usePathname();
  const mobileMode = useIsMobile();
  const phone = useMediaQuery(PHONE_QUERY);
  const mergeOn = useFxSetting('merge') !== false;
  const condenseOn = useFxSetting('condense') !== false;
  const floatOn = useFxSetting('float-act') !== false;

  const [navOpen, setNavOpen] = useState(false);
  const [megaOpen, setMegaOpen] = useState(false);
  const [merged, setMerged] = useState(false);
  const [condensed, setCondensed] = useState(false);
  const [unfolded, setUnfolded] = useState(false);
  // One frame with no motion after a page change: things go straight back.
  const [instant, setInstant] = useState(false);

  const barRef = useRef<HTMLElement>(null);
  const searchHome = useRef<HTMLDivElement>(null);
  // The search box lives in this element and the element moves between the
  // bar and the page header, so it is the same control in both places.
  const [searchBox, setSearchBox] = useState<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = document.createElement('div');
    el.className = 'fx-search-box';
    setSearchBox(el);
    return () => el.remove();
  }, []);

  const placeSearch = useCallback(
    (isMerged: boolean) => {
      if (!searchBox) return;
      const slot = isMerged
        ? document.querySelector('[data-fx-header-merge]')
        : searchHome.current;
      const target = slot ?? searchHome.current;
      if (target && searchBox.parentElement !== target) target.appendChild(searchBox);
    },
    [searchBox],
  );

  const mergedNow = useRef(false);
  useLayoutEffect(() => {
    mergedNow.current = merged;
    placeSearch(merged);
  }, [merged, placeSearch, pathname]);

  useEffect(() => {
    setNavOpen(false);
    setMegaOpen(false);
    setUnfolded(false);
    setInstant(true);
    const raf = requestAnimationFrame(() => setInstant(false));
    return () => cancelAnimationFrame(raf);
  }, [pathname]);

  useEffect(() => {
    const update = () => {
      const y = window.scrollY;
      const isPhone = window.matchMedia(PHONE_QUERY).matches;
      const hasHeader = Boolean(document.querySelector('[data-fx-header-merge]'));
      setMerged((prev) =>
        !isPhone && mergeOn && hasHeader ? nextMerged(prev, y) : false,
      );
      if (isPhone && condenseOn) {
        const actions = document.querySelector('[data-fx-header-actions]');
        const barBottom = barRef.current?.getBoundingClientRect().bottom ?? 0;
        setCondensed((prev) =>
          nextCondensed(prev, {
            y,
            actionBottom: actions ? actions.getBoundingClientRect().bottom : null,
            barBottom,
          }),
        );
      } else {
        setCondensed(false);
      }
      // The page header was replaced under the moved search box: put it back.
      if (searchBox && !searchBox.isConnected) placeSearch(mergedNow.current);
    };
    update();
    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    return () => {
      window.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
    };
  }, [mergeOn, condenseOn, pathname, searchBox, placeSearch]);

  useEffect(() => {
    if (!condensed) setUnfolded(false);
  }, [condensed]);

  const folded = condensed && !unfolded;

  return (
    <>
      <FxSystemBannerHost />
      <header
        ref={barRef}
        className="fx-topbar fx-see-through border-b border-(--fx-line) bg-(--fx-surface)/50 text-(--fx-ink)"
        data-merged={merged ? '' : undefined}
        data-condensed={condensed ? '' : undefined}
        data-instant={instant ? '' : undefined}
        aria-hidden={merged ? true : undefined}
        inert={merged ? true : undefined}
      >
        <div className="flex h-full min-w-0 items-center gap-1.5 px-4 lg:gap-3 lg:px-6">
          {mobileMode && (
            <>
              <Drawer
                open={navOpen}
                onOpenChange={setNavOpen}
                direction="left"
                shouldScaleBackground={false}
              >
                <BarTip label="Menu">
                  <DrawerTrigger asChild>
                    <FxIconActionButton mini label="Open navigation" icon="menu" />
                  </DrawerTrigger>
                </BarTip>
                <DrawerContent className="w-[280px] max-w-[280px] gap-0 bg-(--fx-surface) p-0">
                  <DrawerHeader className="gap-0 p-0">
                    <DrawerTitle className="sr-only">Navigation</DrawerTitle>
                  </DrawerHeader>
                  <DrawerBody className="fx-rail-scroll p-0">
                    <FxSideMenu expanded onNavigate={() => setNavOpen(false)} />
                  </DrawerBody>
                </DrawerContent>
              </Drawer>
              <Drawer
                open={megaOpen}
                onOpenChange={setMegaOpen}
                direction="left"
                shouldScaleBackground={false}
              >
                <DrawerTrigger asChild>
                  <Button variant="ghost" mode="icon" aria-label="Open apps menu">
                    <SquareChevronRight className="text-(--fx-ink-3)" />
                  </Button>
                </DrawerTrigger>
                <DrawerContent className="w-[275px] max-w-[275px] gap-0 p-0">
                  <DrawerHeader className="gap-0 p-0">
                    <DrawerTitle className="sr-only">Apps</DrawerTitle>
                  </DrawerHeader>
                  <DrawerBody className="p-0">
                    <MegaMenuMobile />
                  </DrawerBody>
                </DrawerContent>
              </Drawer>
            </>
          )}

          <div
            ref={searchHome}
            className={cn('flex min-w-0 items-center', phone ? 'flex-1' : 'shrink-0')}
          />

          {!mobileMode && <MegaMenu />}

          <div
            className={cn(
              'ms-auto flex shrink-0 items-center gap-1.5 overflow-hidden transition-[max-width,opacity] duration-(--fx-t-layout) ease-(--fx-ease-out)',
              folded ? 'max-w-0 opacity-0' : 'max-w-[480px] opacity-100',
            )}
            inert={folded ? true : undefined}
          >
            <BarTools phone={phone} />
          </div>
          {folded && (
            <BarTip label="More">
              <FxIconActionButton
                mini
                label="Show the top bar buttons"
                icon="more"
                aria-expanded={false}
                onClick={() => setUnfolded(true)}
              />
            </BarTip>
          )}
        </div>
      </header>

      {searchBox && (
        <SearchPortal host={searchBox} phone={phone} condensed={condensed} />
      )}

      <FxJobsSheet />
      {phone && condensed && floatOn && <FloatingMainAction />}
    </>
  );
}

/** The search control, rendered into the box that moves. */
function SearchPortal({
  host,
  phone,
  condensed,
}: {
  host: HTMLDivElement;
  phone: boolean;
  condensed: boolean;
}) {
  return createPortal(
    <SearchDialog
      trigger={
        <Button
          variant="fx-quiet"
          aria-label="Search"
          className={cn(
            'w-full min-w-9 justify-start gap-2 rounded-(--fx-r-m) px-3 font-normal text-(--fx-ink-3) transition-[height] duration-(--fx-t-layout) ease-(--fx-ease-out) sm:w-64',
            phone && condensed ? 'h-9' : 'h-10',
          )}
        >
          <FxIcon name="search" size={16} />
          <span className="hidden sm:inline">Search</span>
        </Button>
      }
    />,
    host,
  );
}
