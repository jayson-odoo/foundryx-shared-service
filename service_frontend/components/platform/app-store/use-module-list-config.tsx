'use client';

import { useMemo } from 'react';
import { useSession } from 'next-auth/react';
import { toast } from 'sonner';
import type { ColumnDef } from '@tanstack/react-table';
import { ArrowUpCircle, Download, Power, RotateCw, Trash2 } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { StatusBadge } from '@/components/platform/status-badge';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type {
  ResourceAction,
  ResourceActionRuntime,
  ResourceListConfig,
} from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import { appStoreService } from '@/services/app-store-service';
import { invalidateInstalledModules } from '@/hooks/use-app-store';
import { moduleBadge, type StoreAction, type StoreModule } from '@/types/app-store';
import { toCsv } from '@/lib/csv';
import { ModuleCardBody, ModuleIcon, MODULE_BADGES } from './module-card-body';

const stop = (e: React.MouseEvent) => e.stopPropagation();

/**
 * The module lifecycle actions (install/update/deactivate/reactivate/uninstall)
 * shared by the list (row + bulk "…"), the card chrome, and the detail/form
 * "…". State-aware via `isVisible`; the run uses `runtime.reload` so each
 * surface refreshes its own data. Own-tenant actions also refresh menu+session.
 */
export function buildModuleActions(
  tenantId: string | undefined,
  update: () => Promise<unknown>,
): ResourceAction<StoreModule>[] {
  const permFor = (a: StoreAction | 'uninstall'): string =>
    tenantId
      ? 'tenants.manage_modules'
      : a === 'install' || a === 'update'
        ? 'app_store.install'
        : a === 'uninstall'
          ? 'app_store.uninstall'
          : 'app_store.deactivate';

  const runAction = async (
    rows: StoreModule[],
    action: StoreAction | 'uninstall',
    runtime: ResourceActionRuntime,
  ) => {
    for (const m of rows) {
      try {
        if (action === 'uninstall') {
          await (tenantId
            ? appStoreService.uninstallForTenant(tenantId, m.name, m.name)
            : appStoreService.uninstall(m.name, m.name));
        } else {
          await (tenantId
            ? appStoreService.actForTenant(tenantId, m.name, action)
            : appStoreService.act(m.name, action));
        }
      } catch (e) {
        toast.error(e instanceof Error ? e.message : `Could not ${action} ${m.title}.`);
      }
    }
    if (!tenantId) await Promise.all([invalidateInstalledModules(), update()]);
    runtime.reload();
  };

  return [
    {
      id: 'install',
      label: 'Install',
      icon: Download,
      surfaces: { row: true, bulk: true, form: true },
      permission: permFor('install'),
      isVisible: (rows) => rows.length > 0 && rows.every((m) => m.status === null && !m.errored),
      run: (rows, rt) => runAction(rows, 'install', rt),
    },
    {
      id: 'update',
      label: 'Update',
      icon: ArrowUpCircle,
      surfaces: { row: true, bulk: true, form: true },
      permission: permFor('update'),
      isVisible: (rows) =>
        rows.length > 0 && rows.every((m) => m.status === 'ACTIVE' && m.updateAvailable),
      run: (rows, rt) => runAction(rows, 'update', rt),
    },
    // T5 fix round 2, S2: Deactivate is fully reversible (Reactivate is one
    // click, data + permission assignments are kept) - exactly the D2 "grace
    // window, no confirm dialog" shape. Migrated to `deferred` for the
    // STOREFRONT (own tenant, scoped from the JWT - the model `deferred`
    // actions assume). The operator CONSOLE path (`tenantId` set) acts on
    // ANOTHER tenant's module state - outside the actor's own tenant scope
    // that `PendingAction`/`park`/`current` are keyed on - so it stays a
    // disclosed plain-confirm carve-out (immediate, not deferred) rather
    // than forcing a cross-tenant park the engine was never built for.
    tenantId
      ? {
          id: 'deactivate',
          label: 'Deactivate',
          icon: Power,
          surfaces: { row: true, bulk: true, form: true },
          permission: permFor('deactivate'),
          isVisible: (rows) => rows.length > 0 && rows.every((m) => m.status === 'ACTIVE'),
          confirm: {
            title: 'Deactivate module?',
            description:
              'Its pages and API stop working until reactivated. All data is kept and permission assignments preserved.',
            confirmLabel: 'Deactivate',
          },
          run: (rows, rt) => runAction(rows, 'deactivate', rt),
        }
      : {
          id: 'deactivate',
          label: 'Deactivate',
          icon: Power,
          surfaces: { row: true, bulk: true, form: true },
          permission: permFor('deactivate'),
          isVisible: (rows) => rows.length > 0 && rows.every((m) => m.status === 'ACTIVE'),
          deferred: { actionKey: 'tenant_modules.deactivate', entityType: 'tenant_module' },
        },
    {
      id: 'reactivate',
      label: 'Reactivate',
      icon: RotateCw,
      surfaces: { row: true, bulk: true, form: true },
      permission: permFor('deactivate'),
      isVisible: (rows) => rows.length > 0 && rows.every((m) => m.status === 'INACTIVE'),
      run: (rows, rt) => runAction(rows, 'reactivate', rt),
    },
    {
      id: 'uninstall',
      label: 'Uninstall',
      icon: Trash2,
      tone: 'destructive',
      surfaces: { row: true, bulk: true, form: true },
      permission: permFor('uninstall'),
      isVisible: (rows) => rows.length > 0 && rows.every((m) => m.status !== null),
      confirm: {
        title: 'Uninstall module?',
        description:
          'This permanently wipes the module data for this workspace and removes its permissions from every role. This cannot be undone.',
        confirmLabel: 'Uninstall',
        input: {
          expected: (rows) => (rows.length === 1 ? rows[0].name : 'UNINSTALL'),
          hint: (rows) =>
            rows.length === 1
              ? `Type "${rows[0].name}" to confirm.`
              : 'Type "UNINSTALL" to confirm.',
        },
      },
      run: (rows, rt) => runAction(rows, 'uninstall', rt),
    },
  ];
}

/**
 * App Store on the Resource shell (closes the deferred migration) - card view
 * by default with a list toggle, lifecycle actions in the row/bulk "…" menu.
 * Pass a `tenantId` to drive the operator console endpoints (acts on ANOTHER
 * tenant); omit it for the caller's own tenant storefront.
 */
export function useModuleListConfig(tenantId?: string): ResourceListConfig<StoreModule> {
  const { update } = useSession();

  return useMemo<ResourceListConfig<StoreModule>>(() => {
    const actions = buildModuleActions(tenantId, update);

    const columns: ColumnDef<StoreModule>[] = [
      {
        id: 'select',
        meta: { reorderable: false },
        header: () => <div onClick={stop}><DataGridTableRowSelectAll /></div>,
        cell: ({ row }) => <div onClick={stop}><DataGridTableRowSelect row={row} /></div>,
        size: 48,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
      {
        id: 'module',
        accessorFn: (r) => r.title,
        meta: { headerTitle: 'Module' },
        header: ({ column }) => <DataGridColumnHeader title="Module" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-center gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted">
              <ModuleIcon module={row.original} className="size-5 text-primary" />
            </div>
            <div className="flex flex-col">
              <span className="font-medium leading-tight">{row.original.title}</span>
              <span className="text-xs text-muted-foreground">{row.original.name}</span>
            </div>
          </div>
        ),
        size: 280,
        enableSorting: true,
      },
      {
        id: 'version',
        accessorFn: (r) => r.version,
        meta: { headerTitle: 'Version' },
        header: ({ column }) => <DataGridColumnHeader title="Version" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {row.original.status !== null
              ? `v${row.original.installedVersion}${row.original.updateAvailable ? ` → v${row.original.version}` : ''}`
              : `v${row.original.version}`}
          </span>
        ),
        size: 140,
        enableSorting: false,
      },
      {
        id: 'status',
        accessorFn: (r) => r.status ?? '',
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-start">
            <StatusBadge status={moduleBadge(row.original)} registry={MODULE_BADGES} size="sm" />
          </div>
        ),
        size: 150,
        enableSorting: false,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => (
          <div onClick={stop} className="flex justify-end">
            <ActionMenu
              actions={actions}
              rows={[row.original]}
              getEntityId={(m) => m.name}
              runtime={{ reload: table.options.meta?.reload ?? (() => {}) }}
              surface="row"
            />
          </div>
        ),
        size: 60,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
    ];

    const fetcher = async (q: ListQuery): Promise<ListResult<StoreModule>> => {
      const all = tenantId ? await appStoreService.catalogForTenant(tenantId) : await appStoreService.catalog();
      let rows = all;
      if (q.search) {
        const s = q.search.toLowerCase();
        rows = rows.filter(
          (m) =>
            m.title.toLowerCase().includes(s) ||
            m.name.toLowerCase().includes(s) ||
            m.description.toLowerCase().includes(s),
        );
      }
      const seg = q.segment ?? 'all';
      if (seg === 'installed') rows = rows.filter((m) => m.status !== null);
      else if (seg === 'available') rows = rows.filter((m) => m.status === null);
      rows = [...rows].sort((a, b) => a.title.localeCompare(b.title));
      const total = rows.length;
      const start = q.page * q.pageSize;
      return { data: rows.slice(start, start + q.pageSize), total, page: q.page };
    };

    const exporter = async (q: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...q, page: 0, pageSize: 10_000 });
      return toCsv(
        ['Module', 'Name', 'Version', 'Status'],
        data.map((m) => [m.title, m.name, m.version, moduleBadge(m)]),
      );
    };

    return {
      viewKey: tenantId ? 'app-store.console' : 'app-store',
      getRowId: (m) => m.name,
      // T5 fix round 2, S2: `StoreModule` is keyed by `name` (no `.id`) - the
      // Deactivate action's `deferred` park/current/cancel calls need an
      // explicit entity id.
      getEntityId: (m) => m.name,
      // Storefront cards/rows open the module detail/form view; the operator
      // console (tenantId set) manages inline via the "…" menu (no own-tenant
      // detail route for another tenant's module).
      rowHref: tenantId ? () => '#' : (m) => `/app-store/${m.name}`,
      fetcher,
      exporter,
      cardRender: (m) => <ModuleCardBody module={m} />,
      defaultView: 'card',
      searchPlaceholder: 'Search modules…',
      searchHints: ['Title', 'Description'],
      exportFilename: 'modules',
      enableStatusViews: false,
      segments: [
        { id: 'all', label: 'All' },
        { id: 'installed', label: 'Installed' },
        { id: 'available', label: 'Available' },
      ],
      defaultSegment: 'all',
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'module', label: 'Module' },
        { id: 'version', label: 'Version' },
        { id: 'status', label: 'Status' },
      ],
      actions,
    };
  }, [tenantId, update]);
}
