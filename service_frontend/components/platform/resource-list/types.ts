import type { ColumnDef, RowData } from '@tanstack/react-table';
import type { LucideIcon } from 'lucide-react';
import type {
  FilterFieldDef,
  ListQuery,
  ListResult,
  SortState,
} from '@/types/resource';

// Row-surface context the shell threads to cell-rendered action menus.
declare module '@tanstack/react-table' {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface TableMeta<TData extends RowData> {
    /** Encoded list query for preserving record-nav on row navigation. */
    resourceCtx?: string;
    /** Global index of the first row on the current page. */
    pageStartIndex?: number;
    /** Refresh the list after a row action. */
    reload?: () => void;
  }
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData extends RowData, TValue> {
    /** When false, the column can't be drag-reordered (e.g. select, actions). */
    reorderable?: boolean;
  }
}

/** Runtime passed to an action's `run` - lets row actions preserve nav ctx + refresh. */
export interface ResourceActionRuntime {
  /** Encoded list query (row surface only) - for preserving record-nav on navigation. */
  ctx?: string;
  /** Global index of the row within the current query (row surface only). */
  index?: number;
  /**
   * The list href a FORM-surface action should navigate to after a delete/
   * trash success (AC-DLA-30 fix round 1, "post-delete navigation") - the
   * SAME href the record's own Back button computes: `config.backHref` with
   * the record's current `ctx`/`i`/`from` reattached, so leaving via a
   * delete restores the exact list state the user came from rather than a
   * bare default path. Form surface only (row/bulk actions already have
   * `ctx` and stay on the list).
   */
  backHref?: string;
  /** Refresh the list after a mutating action. */
  reload: () => void;
}

/** Fields every action shares, regardless of how it runs. */
interface ResourceActionCommon<T> {
  id: string;
  /**
   * Menu label. A function receives the target rows so the label can be derived
   * from state - e.g. a status_engine "advance" action reads the row's allowed
   * next transition and renders "Move to Triaged" instead of a static verb.
   */
  label: string | ((rows: T[]) => string);
  icon?: LucideIcon;
  tone?: 'default' | 'destructive';
  surfaces: { row?: boolean; bulk?: boolean; form?: boolean };
  /** Permission key required to see/run this action (UX gate; backend enforces). */
  permission?: string;
  /** Hide entirely for these rows (e.g. "Restore" only in trashed view). */
  isVisible?: (rows: T[]) => boolean;
  /** Show but disable (e.g. "Send invitation" only for INVITED users). */
  isDisabled?: (rows: T[]) => boolean;
}

/**
 * One entry in an entity's action registry. The SAME action can surface in the
 * row `...` menu, the bulk toolbar, and the form `...` menu (plan 02 §3c).
 *
 * A discriminated union (fix round 1, T5, item 12) - `confirm`/`run` and
 * `deferred` cannot coexist on one action. Before this, `run` was required on
 * EVERY action, so a migrated `confirm:` -> `deferred:` action kept a `run:`
 * body the shell never calls (`ActionMenu`/`BulkActions` branch on
 * `action.deferred` and return before reaching `run`) - dead code that reads
 * as live. TypeScript now rejects supplying both.
 */
export type ResourceAction<T> =
  | (ResourceActionCommon<T> & {
      /**
       * When set, a confirm dialog gates the action - RESERVED for the
       * disclosed typed-confirmation carve-outs (module uninstall, tenant
       * purge, and Documents > Shares' BULK revoke - T5 fix round 2, S1;
       * D2/D13): every other destructive/reversible action uses `deferred`
       * instead (the grace-window engine, sprint-4/23 T5). See
       * `confirm-action-dialog.tsx` for the full disclosed list.
       */
      confirm?: {
        title: string;
        description?: string;
        confirmLabel?: string;
        /**
         * Typed confirmation (sprint-2/02 - module-uninstall UX): the confirm
         * button stays disabled until the user types `expected(rows)`
         * exactly. For irreversible actions (hard delete).
         */
        input?: { expected: (rows: T[]) => string; hint?: (rows: T[]) => string };
      };
      deferred?: undefined;
      run: (rows: T[], runtime: ResourceActionRuntime) => void | Promise<void>;
    })
  | (ResourceActionCommon<T> & {
      confirm?: undefined;
      /**
       * Deferred (grace-window) action (sprint-4/23 T5, D2/AC-DLA-43): no
       * confirm dialog - the action parks on the server for the tenant-
       * configured window (10s destructive / 5s reversible, read from
       * `tenant_settings` - never authored here, so no `window` field: fix
       * round 1 item 12 removed the field this type used to carry, which no
       * caller ever read) and applies when it lapses. `actionKey` is the
       * backend registry key (`<entity>.<verb>`,
       * `app/deferred_actions/registry.py`). `run` is NOT called by the
       * shell - the shell drives `useDeferredAction` itself, so a
       * `deferred` action has no `run`. `entityType` (the deferred-actions
       * registry's entity type, e.g. `"user"`) is co-located here rather
       * than threaded as a new prop through every
       * ActionMenu/BulkActions/ResourceForm call site (AC-DLA-43's shape
       * omits it - a deliberate, disclosed addition; see the T5 report).
       */
      deferred: {
        actionKey: string;
        entityType: string;
        /**
         * A static park payload the server's handler reads (fix round 1, T5,
         * item 15) - e.g. a toggle action's target state
         * (`{ active: !rows[0].isActive }`). A function of the rows being
         * acted on so a toggle's target can be derived from current state;
         * omit for an action that needs no payload.
         */
        payload?: (rows: T[]) => Record<string, unknown>;
      };
      run?: undefined;
    });

export interface ExportColumn {
  id: string;
  label: string;
}

/** The per-entity config that drives `ResourceList`. New entity = write one of these. */
export interface ResourceListConfig<T extends object> {
  /** Stable key for per-user column prefs (e.g. 'users.list'). */
  viewKey: string;
  /**
   * Overrides `PageHeader`'s auto-resolved (menu-derived) title. Omit for the
   * common case - the sidebar entry's own label already reads right.
   */
  pageTitle?: string;
  /** Optional meta line under the `PageHeader` breadcrumb trail. */
  pageDescription?: import('react').ReactNode;
  columns: ColumnDef<T>[];
  /**
   * Optional card renderer. When set, the list offers a card/list view toggle
   * (persisted per `viewKey`); this returns the card BODY - the shell wraps it
   * with the selection checkbox + row action menu chrome. The card grid reuses
   * the same data/search/filter/segment/pagination as the table.
   */
  cardRender?: (row: T) => import('react').ReactNode;
  /** Initial view when `cardRender` is set (default 'list'). */
  defaultView?: 'card' | 'list';
  getRowId: (row: T) => string;
  /**
   * Opt-in drag-to-reorder ROWS (order = the entity's manual priority). When set,
   * the table renders a left grip handle per row and persists the new id order via
   * `onReorder`. Row order should be the fetcher's default order (disable column
   * sorting so drag order is meaningful). Mutually exclusive with column-drag.
   */
  rowReorder?: { onReorder: (orderedIds: string[]) => void | Promise<void> };
  /** Base form path for a row; the shell appends ctx + index for record-nav. */
  rowHref: (row: T) => string;
  /**
   * Inline master-detail: when set, a row click calls this instead of navigating
   * (rowHref is ignored). Receives the row, its index on the page, and the page
   * rows - used by `<MasterDetail>` to open a detail panel with record-nav.
   */
  onRowSelect?: (row: T, index: number, rows: T[]) => void;
  fetcher: (query: ListQuery) => Promise<ListResult<T>>;
  /**
   * Omit (rather than a no-op returning `''`) when the list has nothing to
   * export - the shell hides the Export button entirely when `exportColumns`
   * is empty (T7 fix round 1: a no-op exporter still rendered an Export
   * button that produced an empty file).
   */
  exporter?: (
    query: ListQuery,
    columns: string[],
    ids?: string[],
  ) => Promise<string>;
  filterFields: FilterFieldDef[];
  exportColumns: ExportColumn[];
  actions: ResourceAction<T>[];
  /**
   * Row id extractor for a bulk `deferred` action's park (fix round 1, T5,
   * item 15) - defaults to `getRowId`. Only needed when a bulk-surfaced
   * deferred action's registered `entityId` isn't the row's own id (e.g. a
   * parent-owned join row keyed off a composite id the row type doesn't
   * carry, like the ideation BR<->idea unlink).
   */
  getEntityId?: (row: T) => string;
  searchPlaceholder?: string;
  /**
   * Human labels for the fields the general search matches (e.g. ['Name',
   * 'Email']). Shown in a friendly "what can I search?" hint beside the box.
   */
  searchHints?: string[];
  defaultSort?: SortState;
  /** Show the Active | Trashed segmented control (default true). */
  enableStatusViews?: boolean;
  /**
   * Per-entity labels for the status-view toggle (default Active | Trashed).
   * The underlying StatusView semantics stay 'active' | 'trashed' - e.g.
   * tenants relabel 'trashed' as "Archived" (soft archive, plan 07 §4).
   */
  statusViewLabels?: { active: string; trashed: string };
  /**
   * N-way segmented control for entities with more views than Active|Trashed
   * (e.g. email log All|Pending|Sent|Failed|Cancelled). When set it REPLACES
   * the binary status views; the selected id rides ListQuery.segment. Row
   * selection clears on switch (same invariant as status views).
   */
  segments?: { id: string; label: string }[];
  /** Initial segment id (default = first entry). */
  defaultSegment?: string;
  /** Filename stem for CSV export (default 'export'). */
  exportFilename?: string;
  createLabel?: string;
  onCreate?: () => void;
  /** Permission key required to show the create button (UX gate). */
  createPermission?: string;
  /**
   * Opt-in bulk import (plan sprint-3/09, F8). When set AND the user holds
   * `writePermission`, the toolbar renders an Import button → the import wizard.
   * `context` (optional) scopes an embedded-list import to a parent record (D17).
   */
  importer?: {
    entityType: string;
    writePermission: string;
    context?: Record<string, unknown>;
  };
}
