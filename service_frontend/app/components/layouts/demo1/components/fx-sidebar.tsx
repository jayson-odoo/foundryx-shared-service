'use client';

/**
 * The Foundryx UIUX side panel (playbook 0.71.0 "Left side panel", "Menu
 * groups"), selected by `sidebar.tsx` only while the switch is on.
 *
 * - Hides to an icon rail, max(64px, 5% width); hover or keyboard focus opens
 *   it over the page; it waits (setting "Wait before it folds to icons", 0.3
 *   s), then slides shut over 0.65 s. A pin keeps it open and moves the page
 *   over; the pin is remembered per browser and shows only while open.
 * - Groups open by hover and stay open while the panel is open; clicking a
 *   group's name pins it open or unpins it. Hover-opened groups fold when the
 *   panel folds to its rail.
 * - The menu is the same one the legacy panel shows: the same `filterMenu`
 *   gating (permission, module, platform) and the same current-page matching.
 *
 * It uses its own `fx-rail` class, never `.sidebar`, so the legacy collapse
 * rules in css/demos/demo1.css (and the reduced-motion reset of `.sidebar`,
 * which would stop the slide the playbook keeps) never reach it. Its look and
 * motion live in css/demos/demo1.css under `[data-fx="on"]`.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ChevronDown } from 'lucide-react';
import { useSession } from 'next-auth/react';
import { MENU_SIDEBAR } from '@/config/menu.config';
import type { MenuConfig, MenuItem } from '@/config/types';
import { toAbsoluteUrl } from '@/lib/helpers';
import { filterMenu } from '@/lib/menu-filter';
import { collectMenuPaths, matchesMenuPath } from '@/lib/menu-path-match';
import { cn } from '@/lib/utils';
import { useInstalledModules } from '@/hooks/use-app-store';
import { useTenantBranding } from '@/hooks/use-branding';
import { useCan } from '@/hooks/use-can';
import { useFxSetting } from '@/hooks/use-fx';
import { usePrefetchOnce } from '@/hooks/use-prefetch-once';
import { useTerminology } from '@/hooks/use-terminology';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { FxIcon } from '@/components/fx/icons';
import { FxTooltip } from '@/components/fx/fx-tooltip';
import { useRail } from '@/components/fx/shell/use-rail';

/** The six side-menu hues (`--fx-menu-1` .. `--fx-menu-6`), by position. */
const HUES = [
  'text-(--fx-menu-1)',
  'text-(--fx-menu-2)',
  'text-(--fx-menu-3)',
  'text-(--fx-menu-4)',
  'text-(--fx-menu-5)',
  'text-(--fx-menu-6)',
];

/** The visible menu and its current-page matcher, exactly as the legacy panel
 *  builds them (sidebar-menu.tsx). */
function useVisibleMenu() {
  const pathname = usePathname();
  const { data: session } = useSession();
  const { can } = useCan();
  const installed = useInstalledModules();
  const showPlatform =
    session?.user?.isPlatformTenant === true && can('tenants.read');
  const visibleMenu = useMemo(
    () =>
      filterMenu(MENU_SIDEBAR, {
        can,
        isModuleActive: installed.isActive,
        modulesReady: installed.ready,
        showPlatform,
      }),
    [can, installed.isActive, installed.ready, showPlatform],
  );
  const menuPaths = useMemo(() => collectMenuPaths(visibleMenu), [visibleMenu]);
  const isCurrent = useCallback(
    (path: string | undefined): boolean =>
      Boolean(path) && matchesMenuPath(path as string, pathname, menuPaths),
    [pathname, menuPaths],
  );
  return { visibleMenu, isCurrent, pathname };
}

const groupKey = (item: MenuItem, index: number) =>
  item.path || `root-${index}`;

function containsCurrent(
  item: MenuItem,
  isCurrent: (path: string | undefined) => boolean,
): boolean {
  if (isCurrent(item.path)) return true;
  return (item.children ?? []).some((child) => containsCurrent(child, isCurrent));
}

interface FxSideMenuProps {
  /** Open as a full panel (false = icon rail). */
  expanded: boolean;
  /** Called after a menu link is followed (the phone drawer closes). */
  onNavigate?: () => void;
}

/**
 * The menu itself: the rail's content, and the phone drawer's (always
 * expanded there).
 */
export function FxSideMenu({ expanded, onNavigate }: FxSideMenuProps) {
  const { visibleMenu, isCurrent, pathname } = useVisibleMenu();
  const { labelPlural } = useTerminology();
  const prefetchOnce = usePrefetchOnce();
  const label = (item: MenuItem): string | undefined =>
    item.termKey ? labelPlural(item.termKey) : item.title;

  // Groups pinned open by a click; the current page's group starts open.
  const [pinnedGroups, setPinnedGroups] = useState<Set<string>>(() => new Set());
  // Groups opened by hover: open while the panel is expanded.
  const [hoverGroups, setHoverGroups] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    const current = visibleMenu.findIndex(
      (item) => item.children && containsCurrent(item, isCurrent),
    );
    if (current === -1) return;
    const key = groupKey(visibleMenu[current], current);
    setPinnedGroups((prev) => (prev.has(key) ? prev : new Set(prev).add(key)));
    // Only when the page changes: a group the user folded stays folded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  useEffect(() => {
    if (!expanded) setHoverGroups(new Set());
  }, [expanded]);

  const toggleGroup = (key: string) => {
    const open = pinnedGroups.has(key);
    setPinnedGroups((prev) => {
      const next = new Set(prev);
      if (open) next.delete(key);
      else next.add(key);
      return next;
    });
    if (open) {
      setHoverGroups((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  const hoverGroup = (key: string) => {
    if (!expanded) return;
    setHoverGroups((prev) => (prev.has(key) ? prev : new Set(prev).add(key)));
  };

  const childLink = (item: MenuItem) => (
    <Link
      href={item.path || '#'}
      prefetch={false}
      onPointerEnter={() => item.path && prefetchOnce(item.path)}
      onClick={() => onNavigate?.()}
      aria-current={isCurrent(item.path) ? 'page' : undefined}
      data-current={isCurrent(item.path) ? '' : undefined}
      className={cn(PRESSED_CLASS, 'fx-rail-row fx-rail-child')}
    >
      <span className="fx-rail-hl" aria-hidden="true" />
      <span className="fx-rail-label">{label(item)}</span>
    </Link>
  );

  const children = (items: MenuConfig, depth: number) => (
    <ul className="fx-rail-list">
      {items.map((item, index) => (
        <li key={item.path || `${depth}-${index}`}>
          {item.children ? (
            <NestedGroup
              title={
                item.collapse
                  ? (item.expandTitle ?? label(item) ?? '')
                  : (label(item) ?? '')
              }
            >
              {children(item.children, depth + 1)}
            </NestedGroup>
          ) : item.disabled ? (
            <span className="fx-rail-row fx-rail-child" aria-disabled="true">
              <span className="fx-rail-label">{label(item)}</span>
            </span>
          ) : (
            childLink(item)
          )}
        </li>
      ))}
    </ul>
  );

  let hue = 0;
  return (
    <ul
      className="fx-rail-list fx-side-menu"
      data-expanded={expanded ? '' : undefined}
    >
      {visibleMenu.map((item, index) => {
        if (item.heading) {
          return (
            <li key={`h-${index}`} className="fx-rail-heading">
              <span className="fx-rail-label">{item.heading}</span>
            </li>
          );
        }
        const Icon = item.icon;
        const color = HUES[hue % HUES.length];
        if (Icon) hue += 1;
        const icon = Icon ? (
          <span className={cn('fx-rail-ic', color)}>
            <Icon className="size-[18px]" strokeWidth={2} aria-hidden="true" />
          </span>
        ) : (
          <span className="fx-rail-ic" />
        );

        if (item.children) {
          const key = groupKey(item, index);
          const open =
            expanded && (pinnedGroups.has(key) || hoverGroups.has(key));
          const current = containsCurrent(item, isCurrent);
          return (
            <li key={key} onPointerEnter={() => hoverGroup(key)}>
              <button
                type="button"
                aria-expanded={open}
                data-current={current ? '' : undefined}
                className={cn(PRESSED_CLASS, 'fx-rail-row')}
                onClick={() => toggleGroup(key)}
              >
                <span className="fx-rail-hl" aria-hidden="true" />
                {icon}
                <span className="fx-rail-label">{label(item)}</span>
                <ChevronDown
                  className="fx-rail-chev size-3"
                  strokeWidth={2.5}
                  aria-hidden="true"
                />
              </button>
              <div className="fx-rail-sub" data-open={open ? '' : undefined}>
                <div className="fx-rail-sub-inner">
                  {children(item.children, 1)}
                </div>
              </div>
            </li>
          );
        }

        if (item.disabled) {
          return (
            <li key={`d-${index}`}>
              <span className="fx-rail-row" aria-disabled="true">
                {icon}
                <span className="fx-rail-label">{label(item)}</span>
              </span>
            </li>
          );
        }

        return (
          <li key={item.path || index}>
            <Link
              href={item.path || '#'}
              prefetch={false}
              onPointerEnter={() => item.path && prefetchOnce(item.path)}
              onClick={() => onNavigate?.()}
              aria-current={isCurrent(item.path) ? 'page' : undefined}
              data-current={isCurrent(item.path) ? '' : undefined}
              className={cn(PRESSED_CLASS, 'fx-rail-row')}
            >
              <span className="fx-rail-hl" aria-hidden="true" />
              {icon}
              <span className="fx-rail-label">{label(item)}</span>
              {item.badge && (
                <span className="fx-rail-label fx-rail-badge">{item.badge}</span>
              )}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/** A group below the first level: opens and folds by click only. */
function NestedGroup({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        className={cn(PRESSED_CLASS, 'fx-rail-row fx-rail-child')}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="fx-rail-hl" aria-hidden="true" />
        <span className="fx-rail-label">{title}</span>
        <ChevronDown
          className="fx-rail-chev size-3"
          strokeWidth={2.5}
          aria-hidden="true"
        />
      </button>
      <div className="fx-rail-sub" data-open={open ? '' : undefined}>
        <div className="fx-rail-sub-inner">{children}</div>
      </div>
    </>
  );
}

function RailLogo() {
  const { branding } = useTenantBranding();
  const tile = branding.faviconUrl ?? branding.logoUrl;
  return (
    <Link href="/" className="fx-rail-logo" aria-label="Home">
      <span className="fx-rail-tile">
        <img
          src={tile ?? toAbsoluteUrl('/media/app/mini-logo.svg')}
          className="h-[20px] w-auto max-w-[24px] object-contain"
          alt=""
        />
      </span>
      {branding.logoUrl ? (
        <span className="fx-rail-label">
          <img
            src={branding.logoUrl}
            className="h-[20px] w-auto max-w-[150px] object-contain"
            alt=""
          />
        </span>
      ) : (
        <span className="fx-rail-label">
          <img
            src={toAbsoluteUrl('/media/app/default-logo.svg')}
            className="h-[22px] max-w-none dark:hidden"
            alt=""
          />
          <img
            src={toAbsoluteUrl('/media/app/default-logo-dark.svg')}
            className="hidden h-[22px] max-w-none dark:block"
            alt=""
          />
        </span>
      )}
    </Link>
  );
}

export function FxSidebar() {
  const wait = Number(useFxSetting('rail-wait') ?? 0.3);
  const rail = useRail(wait);
  const pinLabel = rail.pinned ? 'Unpin side panel' : 'Pin side panel open';

  return (
    <nav
      aria-label="Main menu"
      className="fx-rail fx-see-through"
      data-open={rail.expanded ? '' : undefined}
      data-pinned={rail.pinned ? '' : undefined}
      {...rail.handlers}
    >
      <div className="fx-rail-head">
        <RailLogo />
        <FxTooltip label={pinLabel}>
          <button
            type="button"
            aria-label={pinLabel}
            aria-pressed={rail.pinned}
            tabIndex={rail.expanded ? undefined : -1}
            className={cn(PRESSED_CLASS, 'fx-rail-pin')}
            onClick={rail.togglePin}
          >
            <FxIcon name={rail.pinned ? 'unpin' : 'pin'} size={16} />
          </button>
        </FxTooltip>
      </div>
      <div className="fx-rail-scroll">
        <FxSideMenu expanded={rail.expanded} />
      </div>
    </nav>
  );
}
