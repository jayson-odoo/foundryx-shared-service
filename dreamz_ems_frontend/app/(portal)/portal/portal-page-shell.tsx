'use client';

/**
 * Portal surface page chrome (plan sprint-4/06 slice 2). Reuses the SAME
 * `PortalNav` (sidebar + global event filter pill) the dashboard uses, then
 * renders the surface body in the main column. The active nav item routes back
 * to its surface; the dashboard link is "Dashboard". Responsive: nav collapses
 * behind the hamburger < lg (handled inside PortalNav).
 */
import { useRouter } from 'next/navigation';
import { usePortalSurfaces } from '@/hooks/use-portal-surfaces';
import { unionContexts } from '@/lib/portal-context';
import { usePortalFilter } from '@/providers/portal-filter-provider';
import { PortalNav } from './portal-nav';

const SURFACE_ROUTE: Record<string, string> = {
  my_submissions: '/portal/submissions',
  my_reviews: '/portal/reviews',
  decisions: '/portal/decisions',
};

export interface PortalPageShellProps {
  /** The surface key this page renders (highlights its nav item). */
  surfaceKey: string;
  title: string;
  description?: string;
  children: React.ReactNode;
}

export function PortalPageShell({
  surfaceKey,
  title,
  description,
  children,
}: PortalPageShellProps) {
  const router = useRouter();
  const { surfaces } = usePortalSurfaces();
  const { activeContextKey } = usePortalFilter();
  const contextOptions = unionContexts(surfaces);

  const onSelectSurface = (key: string) => {
    const route = SURFACE_ROUTE[key] ?? '/portal/dashboard';
    const href = activeContextKey
      ? `${route}?ctx=${encodeURIComponent(activeContextKey)}`
      : route;
    router.push(href);
  };

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <PortalNav
        surfaces={surfaces}
        contextOptions={contextOptions}
        activeSurfaceKey={surfaceKey}
        onSelectSurface={onSelectSurface}
      />
      <main className="min-w-0 flex-1 p-4 sm:p-6 lg:p-8">
        <header className="mb-6 space-y-1">
          <h1 className="font-heading text-2xl font-semibold tracking-tight text-mono">
            {title}
          </h1>
          {description && (
            <p className="text-sm text-muted-foreground">{description}</p>
          )}
        </header>
        {children}
      </main>
    </div>
  );
}
