'use client';

import { useState } from 'react';
import { signOut } from 'next-auth/react';
import { LayoutGrid, LogOut, Menu, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { SearchSelect } from '@/components/platform/search-select';
import { useTenantBranding } from '@/hooks/use-branding';
import type { PortalSurface } from '@/services/portal-surface-service';
import type { PortalContextOption } from '@/lib/portal-context';
import { usePortalFilter } from '@/providers/portal-filter-provider';

/**
 * Portal nav chrome (Cluster E, slice 0b — AC-06-25). Surface-first: a list of
 * the Profile's accessible surfaces + the GLOBAL event/context filter pill that
 * narrows every surface to one event. White-label: a branded tenant shows its
 * NAME (never the Dreamz wordmark). Responsive: the sidebar collapses behind a
 * hamburger < lg (drawer); the filter pill + surfaces stack on mobile.
 */
export interface PortalNavProps {
  surfaces: PortalSurface[];
  contextOptions: PortalContextOption[];
  /** The surface key currently in view (anchors highlight); optional. */
  activeSurfaceKey?: string | null;
  onSelectSurface?: (key: string) => void;
}

export function PortalNav({
  surfaces,
  contextOptions,
  activeSurfaceKey,
  onSelectSurface,
}: PortalNavProps) {
  const { branding } = useTenantBranding();
  const { activeContextKey, setActiveContextKey } = usePortalFilter();
  const [mobileOpen, setMobileOpen] = useState(false);

  const brandName = branding.isBranded
    ? branding.tenantName || branding.appName || 'Portal'
    : 'Portal';

  const surfaceList = (
    <nav className="flex flex-col gap-1" aria-label="Portal surfaces">
      {surfaces.map((surface) => {
        const active = surface.key === activeSurfaceKey;
        return (
          <button
            key={surface.key}
            type="button"
            onClick={() => {
              onSelectSurface?.(surface.key);
              setMobileOpen(false);
            }}
            className={cn(
              'flex items-center gap-2.5 rounded-lg px-3 py-2 text-start text-sm font-medium transition-colors',
              active
                ? 'bg-primary/10 text-primary'
                : 'text-foreground hover:bg-muted',
            )}
          >
            <LayoutGrid className="size-4 shrink-0" />
            <span className="truncate">{surface.label}</span>
          </button>
        );
      })}
    </nav>
  );

  return (
    <>
      {/* Mobile top bar — hamburger + brand + filter. */}
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3 lg:hidden">
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Open menu"
            onClick={() => setMobileOpen(true)}
          >
            <Menu className="size-5" />
          </Button>
          {branding.isBranded && branding.logoUrl ? (
            <img src={branding.logoUrl} alt={brandName} className="h-6 w-auto" />
          ) : (
            <span className="font-heading text-base font-semibold text-mono">
              {brandName}
            </span>
          )}
        </div>
        <div className="w-40">
          <ContextFilterPill
            options={contextOptions}
            value={activeContextKey}
            onChange={setActiveContextKey}
          />
        </div>
      </div>

      {/* Mobile drawer. */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-black/40"
            onClick={() => setMobileOpen(false)}
          />
          <div className="absolute inset-y-0 start-0 flex w-72 max-w-[80%] flex-col gap-4 bg-background p-4 shadow-xl">
            <div className="flex items-center justify-between">
              <span className="font-heading text-base font-semibold text-mono">
                {brandName}
              </span>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Close menu"
                onClick={() => setMobileOpen(false)}
              >
                <X className="size-5" />
              </Button>
            </div>
            {surfaceList}
            <div className="mt-auto">
              <Button
                variant="outline"
                className="w-full"
                onClick={() => signOut({ callbackUrl: '/portal/login' })}
              >
                <LogOut className="size-3.5" /> Sign out
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Desktop sidebar. */}
      <aside className="hidden w-64 shrink-0 flex-col gap-5 border-e border-border p-5 lg:flex">
        <div className="flex items-center gap-2">
          {branding.isBranded && branding.logoUrl ? (
            <img src={branding.logoUrl} alt={brandName} className="h-7 w-auto" />
          ) : (
            <span className="font-heading text-lg font-semibold text-mono">
              {brandName}
            </span>
          )}
        </div>

        <div className="space-y-1.5">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Event
          </span>
          <ContextFilterPill
            options={contextOptions}
            value={activeContextKey}
            onChange={setActiveContextKey}
          />
        </div>

        {surfaceList}

        <div className="mt-auto">
          <Button
            variant="outline"
            className="w-full"
            onClick={() => signOut({ callbackUrl: '/portal/login' })}
          >
            <LogOut className="size-3.5" /> Sign out
          </Button>
        </div>
      </aside>
    </>
  );
}

/**
 * The global event/context filter pill — a SearchSelect (the only dropdown
 * primitive). An "All events" sentinel clears the filter (shows items across
 * contexts).
 */
const ALL_EVENTS = '__all__';

function ContextFilterPill({
  options,
  value,
  onChange,
}: {
  options: PortalContextOption[];
  value: string | null;
  onChange: (key: string | null) => void;
}) {
  return (
    <SearchSelect
      ariaLabel="Filter by event"
      placeholder="All events"
      searchPlaceholder="Search events…"
      emptyText="No events."
      options={[
        { label: 'All events', value: ALL_EVENTS },
        ...options.map((o) => ({ label: o.label, value: o.key })),
      ]}
      value={value ?? ALL_EVENTS}
      onChange={(v) => onChange(v === ALL_EVENTS ? null : v)}
    />
  );
}
