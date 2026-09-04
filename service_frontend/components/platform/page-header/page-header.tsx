'use client';

import { Fragment, type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { MENU_SIDEBAR } from '@/config/menu.config';
import { cn } from '@/lib/utils';
import { useMenu } from '@/hooks/use-menu';
import { useTerminology } from '@/hooks/use-terminology';
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';

export interface PageHeaderCrumb {
  label: string;
  href?: string;
}

export interface PageHeaderProps {
  /**
   * Explicit title. Omit to auto-resolve from the current sidebar entry
   * (termKey-aware, mirrors the retired toolbar page-title default) - most
   * list pages don't need to pass one.
   */
  title?: ReactNode;
  eyebrow?: string;
  /** Overrides the sidebar-derived trail (a page the sidebar doesn't name). */
  crumbs?: PageHeaderCrumb[];
  /** Right-hand slot - a list's primary Create button, a form's Back button. */
  actions?: ReactNode;
  /** Optional meta line under the trail (kept from the retired `ToolbarDescription`). */
  description?: ReactNode;
  className?: string;
}

const ROOT_CRUMB: PageHeaderCrumb = { label: 'Dashboard', href: '/' };

/**
 * Drops a crumb that repeats the label of the one right before it - the
 * sidebar nests groups like "Dashboards > Light Sidebar" whose labels can
 * collide with the page's own resolved title.
 */
function dedupe(crumbs: PageHeaderCrumb[]): PageHeaderCrumb[] {
  return crumbs.filter(
    (crumb, index) =>
      index === crumbs.length - 1 || crumbs[index + 1].label !== crumb.label,
  );
}

/**
 * The one page-title header (AC-DLA-27, plan 23 D6): title at one scale
 * (`font-heading`), crumbs derived from `useMenu().getBreadcrumb(MENU_SIDEBAR)`
 * unless `crumbs` overrides, actions on the right. `ResourceList` renders this
 * above its card (the primary Create button is the `actions` slot);
 * `ResourceForm` renders it as the toolbar row (Back is the `actions` slot).
 * Every page under `app/(protected)` renders exactly one.
 */
export function PageHeader({
  title,
  eyebrow,
  crumbs,
  actions,
  description,
  className,
}: PageHeaderProps) {
  const pathname = usePathname() ?? '/';
  const { getBreadcrumb, getCurrentItem } = useMenu(pathname);
  const { labelPlural } = useTerminology();

  const currentItem = getCurrentItem(MENU_SIDEBAR);
  const menuLabel = currentItem?.termKey
    ? labelPlural(currentItem.termKey)
    : currentItem?.title;
  const resolvedTitle: ReactNode = title ?? menuLabel ?? '';

  const chain: PageHeaderCrumb[] = getBreadcrumb(MENU_SIDEBAR)
    .filter((item) => Boolean(item.title))
    .map((item) => ({
      label: item.termKey ? labelPlural(item.termKey) : (item.title as string),
      href: item.path,
    }));

  const trail = crumbs?.length
    ? dedupe([ROOT_CRUMB, ...crumbs])
    : dedupe([
        ROOT_CRUMB,
        ...chain,
        ...(typeof resolvedTitle === 'string' &&
        resolvedTitle &&
        chain[chain.length - 1]?.label !== resolvedTitle
          ? [{ label: resolvedTitle }]
          : []),
      ]);

  return (
    <div
      className={cn(
        'flex flex-wrap items-end justify-between gap-3',
        className,
      )}
    >
      <div className="flex min-w-0 flex-col gap-1">
        {eyebrow && (
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {eyebrow}
          </span>
        )}
        <h1 className="min-w-0 break-words font-heading text-xl font-semibold leading-tight text-foreground">
          {resolvedTitle}
        </h1>
        <Breadcrumb>
          <BreadcrumbList>
            {trail.map((crumb, index) => {
              // The LAST crumb is the only `aria-current="page"` (AC-DLA-27) -
              // even when it happens to carry an `href` (the page IS that
              // sidebar entry), it renders as `BreadcrumbPage`, never a link.
              const isLast = index === trail.length - 1;
              return (
                <Fragment key={`${crumb.label}-${index}`}>
                  <BreadcrumbItem>
                    {isLast ? (
                      <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                    ) : crumb.href ? (
                      <BreadcrumbLink asChild>
                        <Link href={crumb.href}>{crumb.label}</Link>
                      </BreadcrumbLink>
                    ) : (
                      <span>{crumb.label}</span>
                    )}
                  </BreadcrumbItem>
                  {!isLast && <BreadcrumbSeparator />}
                </Fragment>
              );
            })}
          </BreadcrumbList>
        </Breadcrumb>
        {description && (
          <div className="text-sm text-muted-foreground">{description}</div>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export default PageHeader;
