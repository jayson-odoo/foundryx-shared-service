'use client';

import { useState, type ComponentType } from 'react';
import {
  Blocks,
  ClipboardList,
  LifeBuoy,
  Loader2,
  MessageSquare,
  ReceiptText,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardFooter } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ClampedText } from '@/components/platform/clamped-text';
import { StatusBadge, type StatusRegistry } from '@/components/platform/status-badge';
import {
  moduleBadge,
  type StoreAction,
  type StoreModule,
  type StoreModuleBadge,
} from '@/types/app-store';

/**
 * One App Store card (plan 08 §8) — icon, title, description, version,
 * StatusBadge + lifecycle actions. Shared verbatim between the tenant
 * storefront (/app-store) and the console tenant-detail Modules tab; the
 * caller decides WHICH actions the viewer may take via `canAct` (tenant =
 * app_store.* keys, operator = tenants.manage_modules).
 */

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

export interface ModuleCardProps {
  module: StoreModule;
  /** May the viewer take this action? (UX gate — backend re-checks.) */
  canAct: (action: StoreAction | 'uninstall') => boolean;
  /** True while ANY action runs on this module (disables the card's buttons). */
  busy: boolean;
  onAction: (name: string, action: StoreAction) => Promise<boolean>;
  onUninstall: (name: string, confirmName: string) => Promise<boolean>;
}

export function ModuleCard({ module, canAct, busy, onAction, onUninstall }: ModuleCardProps) {
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);
  const [confirmUninstall, setConfirmUninstall] = useState(false);
  const [typedName, setTypedName] = useState('');

  const badge = moduleBadge(module);
  const installed = module.status !== null;
  const Icon = (module.icon && MODULE_ICONS[module.icon]) || Blocks;

  const closeUninstall = () => {
    setConfirmUninstall(false);
    setTypedName('');
  };

  return (
    <Card data-testid={`module-card-${module.name}`} className="flex flex-col">
      <CardContent className="flex grow flex-col gap-3 p-5">
        <div className="flex items-start justify-between gap-2">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-muted">
            <Icon className="size-6 text-primary" />
          </div>
          <StatusBadge status={badge} registry={MODULE_BADGES} size="sm" />
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

        {/* Module platform v2 (plan sprint-3/10) — dependency + errored UX. */}
        {(module.requires?.length || module.optional?.length) && (
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
          <p className="text-destructive text-xs">
            This module failed to load and is unavailable.
          </p>
        )}
        {!installed && !module.errored && module.availabilityOk === false && (
          <p className="text-xs text-amber-600 dark:text-amber-500">
            Needs required modules installed first — installing will offer to add them.
          </p>
        )}
      </CardContent>

      <CardFooter className="flex flex-wrap gap-2 border-t p-4">
        {busy && <Loader2 className="size-4 animate-spin text-muted-foreground" />}

        {!installed && canAct('install') && (
          <Button
            size="sm"
            disabled={busy || module.errored}
            onClick={() => onAction(module.name, 'install')}
          >
            Install
          </Button>
        )}

        {installed && module.updateAvailable && module.status === 'ACTIVE' && canAct('install') && (
          <Button size="sm" disabled={busy} onClick={() => onAction(module.name, 'update')}>
            Update
          </Button>
        )}

        {module.status === 'ACTIVE' && canAct('deactivate') && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => setConfirmDeactivate(true)}
          >
            Deactivate
          </Button>
        )}

        {module.status === 'INACTIVE' && canAct('deactivate') && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => onAction(module.name, 'reactivate')}
          >
            Reactivate
          </Button>
        )}

        {installed && canAct('uninstall') && (
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive hover:text-destructive"
            disabled={busy}
            onClick={() => setConfirmUninstall(true)}
          >
            Uninstall
          </Button>
        )}
      </CardFooter>

      {/* Deactivate — plain confirm: data kept, routes 403, menu hidden (plan 08 §5). */}
      <AlertDialog open={confirmDeactivate} onOpenChange={setConfirmDeactivate}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Deactivate {module.title}?</AlertDialogTitle>
            <AlertDialogDescription>
              {module.title} will be switched off for this workspace — its pages and API stop
              working until reactivated. All data is kept and permission assignments are
              preserved.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => void onAction(module.name, 'deactivate')}>
              Deactivate
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Uninstall — typed confirmation, irreversible data wipe (plan 08 §5).
          Deliberately NOT the shared ConfirmActionDialog (resource-actions):
          this one needs busy-state + stay-open-on-failure (server rejects a
          wrong confirm), which the fire-and-close action contract doesn't
          model. If a third typed-confirm needs those semantics, extend the
          shared dialog instead of copying this. */}
      <Dialog open={confirmUninstall} onOpenChange={(open) => !open && closeUninstall()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Uninstall {module.title}?</DialogTitle>
            <DialogDescription className="text-destructive">
              This permanently wipes all {module.title} data for this workspace and removes its
              permissions from every role. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-2">
            <p className="text-sm text-muted-foreground">
              Type <span className="font-mono font-medium text-foreground">{module.name}</span> to
              confirm.
            </p>
            <Input
              autoFocus
              value={typedName}
              placeholder={module.name}
              onChange={(e) => setTypedName(e.target.value)}
              aria-label="Confirm module name"
            />
          </DialogBody>
          <DialogFooter>
            <Button variant="outline" onClick={closeUninstall}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={typedName !== module.name || busy}
              onClick={async () => {
                const ok = await onUninstall(module.name, typedName);
                if (ok) closeUninstall();
              }}
            >
              Uninstall
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
