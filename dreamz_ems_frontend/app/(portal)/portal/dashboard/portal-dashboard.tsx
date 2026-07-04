'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useSession } from 'next-auth/react';
import { ArrowRight, LayoutGrid, LoaderCircleIcon } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { usePortalSurfaces } from '@/hooks/use-portal-surfaces';
import { usePortalFilter } from '@/providers/portal-filter-provider';
import {
  contextLabel,
  contextsForSurface,
  filterSurfaces,
  unionContexts,
} from '@/lib/portal-context';
import type {
  PortalProfile,
} from '@/app/api/portal-auth/[...nextauth]/portal-auth-options';
import type { PortalSurface } from '@/services/portal-surface-service';
import { PortalNav } from '../portal-nav';

/** Surface key → its dedicated portal route (slice 2 surfaces). A surface
 * without a route renders an overview-only card. */
const SURFACE_ROUTE: Record<string, string> = {
  my_submissions: '/portal/submissions',
  my_reviews: '/portal/reviews',
  decisions: '/portal/decisions',
};

/**
 * The unified portal dashboard body (AC-06-24/25). Composes ONE section per
 * accessible surface (the backend gates the visible set). A section renders only
 * if returned; its contexts are narrowed by the global filter pill. Unfiltered,
 * every context is shown with the context labelled per row. The real surface
 * bodies land in slices 1/2 — here each section proves composition + gating with
 * a thin placeholder body listing its scoped contexts.
 *
 * Split out from the route page so Vitest can mount it directly (mocking the
 * surface service + the portal filter).
 */
function surfaceHref(key: string, activeContextKey: string | null): string | null {
  const route = SURFACE_ROUTE[key];
  if (!route) return null;
  return activeContextKey ? `${route}?ctx=${encodeURIComponent(activeContextKey)}` : route;
}

export function PortalDashboard() {
  const { data: session } = useSession();
  const { surfaces, loading, error } = usePortalSurfaces();
  const { activeContextKey } = usePortalFilter();
  const [activeSurfaceKey, setActiveSurfaceKey] = useState<string | null>(null);

  const profile = (session as unknown as { profile?: PortalProfile } | null)
    ?.profile;
  const greeting = profile?.fullName || profile?.email || 'there';

  const contextOptions = unionContexts(surfaces);
  const visible = filterSurfaces(surfaces, activeContextKey);

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <PortalNav
        surfaces={surfaces}
        contextOptions={contextOptions}
        activeSurfaceKey={activeSurfaceKey}
        onSelectSurface={setActiveSurfaceKey}
      />

      <main className="min-w-0 flex-1 p-4 sm:p-6 lg:p-8">
        <header className="mb-6 space-y-1">
          <h1 className="font-heading text-2xl font-semibold tracking-tight text-mono">
            Welcome back, {greeting}
          </h1>
        </header>

        {loading ? (
          <div className="flex items-center justify-center py-24 text-muted-foreground">
            <LoaderCircleIcon className="size-6 animate-spin" />
          </div>
        ) : error ? (
          <p className="py-12 text-center text-sm text-destructive">{error}</p>
        ) : visible.length === 0 ? (
          <p className="py-12 text-center text-sm text-muted-foreground">
            Nothing here yet.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
            {visible.map((surface) => (
              <SurfaceSection
                key={surface.key}
                surface={surface}
                activeContextKey={activeContextKey}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

function SurfaceSection({
  surface,
  activeContextKey,
}: {
  surface: PortalSurface;
  activeContextKey: string | null;
}) {
  const contexts = contextsForSurface(surface, activeContextKey);
  const href = surfaceHref(surface.key, activeContextKey);

  return (
    <section
      data-surface={surface.key}
      className="flex flex-col gap-3 rounded-xl border border-border bg-card p-5"
    >
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <LayoutGrid className="size-4" />
        </span>
        <div className="min-w-0 space-y-0.5">
          <h2 className="truncate font-medium text-mono">{surface.label}</h2>
          {surface.description && (
            <p className="text-xs text-muted-foreground">{surface.description}</p>
          )}
        </div>
      </div>

      {/* Thin placeholder body — slices 1/2 render the real surface. Until then,
          show the surface's scoped contexts (the context per row when
          unfiltered) so gating + context scoping are visibly proven. */}
      {contexts.length > 0 ? (
        <ul className="flex flex-col gap-1.5">
          {contexts.map((ctx, i) => (
            <li
              key={`${ctx.scopeType}:${ctx.scopeId ?? ''}:${i}`}
              data-context={`${ctx.scopeType}:${ctx.scopeId ?? ''}`}
              className="flex items-center justify-between rounded-md bg-muted/50 px-3 py-2 text-sm"
            >
              <span className="text-muted-foreground">{contextLabel(ctx)}</span>
              <Badge variant="secondary" appearance="light" size="sm">
                {ctx.scopeType}
              </Badge>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">No items.</p>
      )}

      {href && (
        <Button variant="outline" size="sm" className="mt-auto self-start" asChild>
          <Link href={href} data-testid={`open-${surface.key}`}>
            Open {surface.label}
            <ArrowRight className="size-3.5" />
          </Link>
        </Button>
      )}
    </section>
  );
}
