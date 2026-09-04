'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { usePathname } from 'next/navigation';
import { CircleCheck, HardDriveDownload, Pencil, PlugZap, Unplug } from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceAction } from '@/components/platform/resource-list';
import { integrationService } from '@/services/integration-service';
import { useJobsActivity } from '@/providers/jobs-activity-provider';
import type { Connection } from '@/types/integration';
import { connectionFormHref, integrationsListPath } from './paths';

/**
 * The Connection action registry - surfaced in the row "…" menu, the bulk
 * toolbar, and the form "…" menu (plan 02 §3c). The wizard's ceremony lives
 * on as Test here + the UNVERIFIED badge (plan 06 D6).
 */
export function useConnectionActions(): ResourceAction<Connection>[] {
  const router = useRouter();
  const pathname = usePathname();
  const { openMigration } = useJobsActivity();

  // Providers that offer NO test declare it with an empty `testLabel` (the
  // meetings notetaker account: verifying it means a real interactive sign-in).
  // Offering Test anyway would either lie about the result or always fail.
  const [noTestProviders, setNoTestProviders] = useState<Set<string>>(new Set());
  useEffect(() => {
    integrationService
      .providers()
      .then((list) =>
        setNoTestProviders(
          new Set(list.filter((p) => !p.testLabel).map((p) => p.provider)),
        ),
      )
      .catch(() => setNoTestProviders(new Set()));
  }, []);

  return useMemo<ResourceAction<Connection>[]>(
    () => [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        permission: 'integrations.manage',
        surfaces: { row: true },
        run: ([connection], rt) => {
          if (!connection) return;
          router.push(
            connectionFormHref(connection.id, { ctx: rt.ctx, index: rt.index, edit: true }),
          );
        },
      },
      {
        id: 'test',
        label: 'Test connection',
        icon: PlugZap,
        permission: 'integrations.manage',
        surfaces: { row: true, form: true },
        isVisible: (rows) => rows.length === 1 && !noTestProviders.has(rows[0].provider),
        run: async ([connection], rt) => {
          if (!connection) return;
          const result = await integrationService.test(connection.id);
          if (result.ok) toast.success(result.message);
          else toast.error(result.message);
          rt.reload();
        },
      },
      {
        id: 'set-active',
        label: 'Set as active',
        icon: CircleCheck,
        permission: 'integrations.manage',
        surfaces: { row: true, form: true },
        // Only a storage connection that ISN'T already the active write-target.
        // Making it active retires the others; new uploads land here.
        isVisible: (rows) =>
          rows.length === 1 && rows[0].type === 'storage' && !rows[0].isActive,
        // Grace-window deferred action (sprint-4/23, T5, D2) - no confirm.
        deferred: { actionKey: 'connections.activate', entityType: 'connection', window: 'reversible' },
        run: async ([connection], rt) => {
          if (!connection) return;
          await integrationService.activate(connection.id);
          toast.success(`${connection.name} is now the active storage bucket.`);
          rt.reload();
        },
      },
      {
        id: 'migrate-storage',
        label: 'Migrate storage',
        icon: HardDriveDownload,
        permission: 'integrations.migrate_storage',
        surfaces: { row: true, form: true },
        // Only for a storage connection - the migration drains this tenant's
        // active storage bucket onto a new one (backend resolves the source).
        isVisible: (rows) => rows.length === 1 && rows[0].type === 'storage',
        run: () => openMigration(),
      },
      {
        id: 'disconnect',
        label: 'Disconnect',
        icon: Unplug,
        tone: 'destructive',
        permission: 'integrations.manage',
        surfaces: { row: true, bulk: true, form: true },
        // Grace-window deferred action (sprint-4/23, T5, D2) - no confirm.
        deferred: { actionKey: 'connections.delete', entityType: 'connection', window: 'destructive' },
        run: async (rows, rt) => {
          for (const row of rows) {
            await integrationService.remove(row.id);
          }
          toast.success(
            rows.length === 1
              ? `${rows[0].name} disconnected.`
              : `${rows.length} connections disconnected.`,
          );
          // From the form surface the record is gone - return to the list,
          // carrying the record's own ctx/i/from (AC-DLA-30 fix round 2) so
          // the list restores exactly where the user left it.
          if (pathname !== integrationsListPath) router.push(rt.backHref ?? integrationsListPath);
          else rt.reload();
        },
      },
    ],
    [router, pathname, openMigration, noTestProviders],
  );
}
