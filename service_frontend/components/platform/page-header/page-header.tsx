'use client';

import { Fragment, type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
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
import { useFx } from '@/hooks/use-fx';
import { FxMainAction } from '@/components/fx/actions/main-action';
import { FxOtherActions } from '@/components/fx/actions/other-actions';
import { usePageActions } from '@/components/fx/actions/page-actions-context';

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
  /**
   * `ResourceForm`'s dirty-guard (`guard(proceed)`, AC-10-16): when supplied,
   * every crumb link routes navigation through it instead of a bare
   * client-side push, so an in-progress edit is never silently discarded by
   * a breadcrumb click. Omitted on every non-form `PageHeader` (list pages
   * have nothing to guard).
   */
  guardNav?: (proceed: () => void) => void;
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
export function PageHeader(props: PageHeaderProps) {
  // Foundryx UIUX switch (playbook-uiux.md): the playbook's frozen header.
  // Off renders the legacy body below, unchanged.
  return useFx() ? <FxPageHeader {...props} /> : <PageHeaderLegacy {...props} />;
}

/** Title and crumb trail, resolved the same way as the legacy header. */
function usePageHeaderTrail(
  title: ReactNode | undefined,
  crumbs: PageHeaderCrumb[] | undefined,
): { resolvedTitle: ReactNode; trail: PageHeaderCrumb[] } {
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
  return { resolvedTitle, trail };
}

/**
 * The Foundryx UIUX page header (playbook 0.71.0 "Actions", "Responsive"):
 * frozen under the top bar on a see-through surface; title and crumbs on the
 * left; at the top right the Other Actions, then the one red action that any
 * component on the page registered (`useRegisterMainAction`), with its
 * blocked reason hanging under it. On phones, when the title would get less
 * than 140px, it takes its own line and the actions stay together under it
 * at the right. `data-fx-header` is where the top bar merges in (F5).
 */
function FxPageHeader({
  title,
  eyebrow,
  crumbs,
  actions,
  description,
  className,
  guardNav,
}: PageHeaderProps) {
  const router = useRouter();
  const { resolvedTitle, trail } = usePageHeaderTrail(title, crumbs);
  const page = usePageActions();
  const main = page.hidden ? null : page.main;
  const hasActions = Boolean(actions) || page.others.length > 0 || main;

  return (
    <div
      data-fx-header=""
      className={cn(
        'fx-see-through sticky top-[calc(var(--header-height,0px)+var(--shell-top-offset,0px))] z-(--fx-z-header) flex flex-wrap items-start justify-between gap-x-3 gap-y-2 bg-(--fx-surface)/50 py-2 text-(--fx-ink)',
        main?.blocked && 'sm:pb-8',
        className,
      )}
    >
      <div className="flex min-w-[140px] flex-1 basis-[140px] flex-col gap-1">
        {eyebrow && (
          <span className="text-xs font-semibold uppercase tracking-wide text-(--fx-ink-3)">
            {eyebrow}
          </span>
        )}
        <h1 className="min-w-0 break-words text-xl font-bold leading-tight text-(--fx-ink)">
          {resolvedTitle}
        </h1>
        <Breadcrumb>
          <BreadcrumbList className="text-(--fx-ink-3)">
            {trail.map((crumb, index) => {
              const isLast = index === trail.length - 1;
              return (
                <Fragment key={`${crumb.label}-${index}`}>
                  <BreadcrumbItem>
                    {isLast ? (
                      <BreadcrumbPage className="text-(--fx-ink-2)">
                        {crumb.label}
                      </BreadcrumbPage>
                    ) : crumb.href ? (
                      <BreadcrumbLink asChild>
                        <Link
                          href={crumb.href}
                          className="transition-[translate] duration-(--fx-t-hover) ease-(--fx-ease-out) hover:-translate-y-px hover:text-(--fx-link)"
                          onClick={(e) => {
                            if (!guardNav) return;
                            if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
                            e.preventDefault();
                            const target = crumb.href as string;
                            guardNav(() => router.push(target));
                          }}
                        >
                          {crumb.label}
                        </Link>
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
          <div className="text-sm text-(--fx-ink-3)">{description}</div>
        )}
      </div>
      {hasActions && (
        <div
          data-fx-header-actions=""
          className="ms-auto flex flex-nowrap items-start gap-2"
        >
          {actions && <div className="flex items-center gap-2">{actions}</div>}
          {page.others.length > 0 && <FxOtherActions actions={page.others} />}
          {main && (
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
          )}
        </div>
      )}
    </div>
  );
}

function PageHeaderLegacy({
  title,
  eyebrow,
  crumbs,
  actions,
  description,
  className,
  guardNav,
}: PageHeaderProps) {
  const pathname = usePathname() ?? '/';
  const router = useRouter();
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
                        <Link
                          href={crumb.href}
                          onClick={(e) => {
                            if (!guardNav) return;
                            // Modifier clicks (open in new tab/window) bypass
                            // the dirty-guard - the browser's own default
                            // handles them, never our SPA push. A middle
                            // click never reaches `onClick` at all (that is
                            // `auxclick`), so `e.button === 1` here was dead.
                            if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
                            e.preventDefault();
                            const target = crumb.href as string;
                            guardNav(() => router.push(target));
                          }}
                        >
                          {crumb.label}
                        </Link>
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
