'use client';

import { type ComponentType } from 'react';
import { Blocks, ClipboardList, LifeBuoy, MessageSquare, ReceiptText } from 'lucide-react';
import { ClampedText } from '@/components/platform/clamped-text';
import { StatusBadge, type StatusRegistry } from '@/components/platform/status-badge';
import { moduleBadge, type StoreModule, type StoreModuleBadge } from '@/types/app-store';

/** Storefront badge registry (shared by card + list surfaces). */
export const MODULE_BADGES: StatusRegistry<StoreModuleBadge> = {
  NOT_INSTALLED: { label: 'Not installed', tone: 'secondary' },
  ACTIVE: { label: 'Active', tone: 'success' },
  INACTIVE: { label: 'Inactive', tone: 'warning' },
  UPDATE_AVAILABLE: { label: 'Update available', tone: 'info' },
};

/** Manifest `icon` string → Lucide component (graceful fallback for unknowns). */
const MODULE_ICONS: Record<string, ComponentType<{ className?: string }>> = {
  'message-square': MessageSquare,
  'life-buoy': LifeBuoy,
  'receipt-text': ReceiptText,
  'clipboard-list': ClipboardList,
};

export function ModuleIcon({ module, className }: { module: StoreModule; className?: string }) {
  const Icon = (module.icon && MODULE_ICONS[module.icon]) || Blocks;
  return <Icon className={className ?? 'size-6 text-primary'} />;
}

/**
 * The card BODY for an App Store module - icon, title, version, description,
 * dependency chips, errored/availability notes + the status badge. Action
 * controls live in the Resource shell's row "…" menu, not here.
 */
export function ModuleCardBody({ module }: { module: StoreModule }) {
  const installed = module.status !== null;
  return (
    <div className="flex grow flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-muted">
          <ModuleIcon module={module} />
        </div>
        <StatusBadge status={moduleBadge(module)} registry={MODULE_BADGES} size="sm" />
      </div>
      <div>
        <h3 className="font-heading text-base font-semibold">{module.title}</h3>
        <p className="text-xs text-muted-foreground">
          {installed
            ? `v${module.installedVersion}${module.updateAvailable ? ` → v${module.version}` : ''}`
            : `v${module.version}`}
        </p>
      </div>
      <ClampedText text={module.description} className="text-sm text-muted-foreground" />

      {Boolean(module.requires?.length || module.optional?.length) && (
        <div className="flex flex-wrap gap-1.5">
          {module.requires?.map((r) => (
            <span
              key={`req-${r.name}`}
              className="rounded bg-muted px-1.5 py-0.5 text-[0.6875rem] text-muted-foreground"
            >
              Requires {r.name}
            </span>
          ))}
          {module.optional?.map((o) => (
            <span
              key={`opt-${o.name}`}
              className="rounded bg-muted px-1.5 py-0.5 text-[0.6875rem] text-muted-foreground"
            >
              Enhances {o.name}
            </span>
          ))}
        </div>
      )}
      {module.errored && (
        <p className="text-destructive text-xs">This module failed to load and is unavailable.</p>
      )}
      {!installed && !module.errored && module.availabilityOk === false && (
        <p className="text-xs text-amber-600 dark:text-amber-500">
          Needs required modules installed first - installing will offer to add them.
        </p>
      )}
    </div>
  );
}
