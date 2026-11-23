'use client';

import { useMemo } from 'react';
import { useSession } from 'next-auth/react';
import { toast } from '@/lib/toast';
import { useFx } from '@/hooks/use-fx';
import type { FxIconRef } from '@/components/fx/icons';
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

/** Other Action icons under the Foundryx UIUX switch (one icon per meaning);
 *  the other lifecycle actions keep their own drawn icons. */
export const MODULE_FX_ICONS: Record<string, FxIconRef> = {
  uninstall: 'trash',
};

/**
 * What the Foundryx UIUX uninstall confirm asks to type (owner decision: the
 * record's name or number replaces the press and hold): one module types its
 * name, several type how many there are. With the switch off the confirm
 * keeps `expected` (the name, or UNINSTALL for several).
 */
export function fxUninstallExpected(rows: Pick<StoreModule, 'name'>[]): string {
  return rows.length === 1 ? rows[0].name : String(rows.length);
}

/** Foundryx UIUX switch only: the look the actions are built for, and who
 *  acts (for the done toast). */
export interface ModuleActionsFx {
  on: boolean;
  byWhom?: string;
}

const FX_DONE_VERB: Record<StoreAction | 'uninstall', string> = {
  install: 'installed',
  update: 'updated',
  deactivate: 'deactivated',
  reactivate: 'reactivated',
  uninstall: 'uninstalled',
};

/**
 * The module lifecycle actions (install/update/deactivate/reactivate/uninstall)
 * shared by the list (row + bulk "…"), the card chrome, and the detail/form
 * "…". State-aware via `isVisible`; the run uses `runtime.reload` so each
 * surface refreshes its own data. Own-tenant actions also refresh menu+session.
 */
export function buildModuleActions(
  tenantId: string | undefined,
  update: () => Promise<unknown>,
  fx: ModuleActionsFx = { on: false },
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
    const done: StoreModule[] = [];
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
        done.push(m);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : `Could not ${action} ${m.title}.`);
      }
    }
    if (!tenantId) await Promise.all([invalidateInstalledModules(), update()]);
    // Foundryx UIUX switch only: what was done, by whom. No Undo: the API
    // has no reverse of an install or uninstall (an uninstall wipes data).
    if (fx.on && done.length > 0) {
      toast.fxDone({
        what:
          done.length === 1
            ? `${done[0].title} ${FX_DONE_VERB[action]}`
            : `${done.length} modules ${FX_DONE_VERB[action]}`,
        byWhom: fx.byWhom,
      });
    }
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
            fxKeepLabel: (rows) => (rows.length === 1 ? 'Keep module on' : 'Keep modules on'),
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
          deferred: {
            actionKey: 'tenant_modules.deactivate',
            entityType: 'tenant_module',
            // Foundryx UIUX switch only: the one-module countdown names it.
            fxName: (rows) => (rows.length === 1 ? rows[0].title : undefined),
          },
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
        // Foundryx UIUX switch: the question names its object, one line says
        // what does not come back, the action is verb + object. Off keeps
        // today's words.
        title: fx.on
          ? (rows) =>
              rows.length === 1 ? `Uninstall ${rows[0].title}?` : `Uninstall ${rows.length} modules?`
          : 'Uninstall module?',
        description: fx.on
          ? 'Its data in this workspace and its permissions on every role are erased and do not come back.'
          : 'This permanently wipes the module data for this workspace and removes its permissions from every role. This cannot be undone.',
        confirmLabel: fx.on
          ? (rows) => (rows.length === 1 ? 'Uninstall module' : `Uninstall ${rows.length} modules`)
          : 'Uninstall',
        fxKeepLabel: (rows) => (rows.length === 1 ? 'Keep module' : 'Keep modules'),
        input: {
          fxExpected: fxUninstallExpected,
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
  const { update, data } = useSession();
  const fxOn = useFx();
  const byWhom = data?.user?.name ?? undefined;

  return useMemo<ResourceListConfig<StoreModule>>(() => {
    const actions = buildModuleActions(tenantId, update, { on: fxOn, byWhom });

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
      // Foundryx UIUX switch only (slice W3-PLATFORM); ignored while off.
      // The storefront has no Create, so no red action; the tenant record's
      // Modules tab shows the smaller states.
      fx: {
        noun: 'modules',
        iconFor: MODULE_FX_ICONS,
        moreActionIds: ['uninstall'],
        columnKind: { status: 'status' },
        cardLines: [['module', 'status'], ['version']],
        compactStates: Boolean(tenantId),
      },
    };
  }, [tenantId, update, fxOn, byWhom]);
}
