'use client';

/**
 * `ResourceList` with the Foundryx UIUX switch on (playbook 0.71.0 "Lists").
 *
 * The same data hooks, services, actions, export, import, segments, status
 * views and row navigation as the legacy list, so the two cannot drift in
 * behaviour; only the presentation changes:
 * - Smart view / Table view toggle at the right of the filter bar, remembered
 *   per list (`useFxListPrefs`); a list with a card renderer keeps its cards
 *   as a third choice.
 * - The Columns panel beside the toggle, one column set per view.
 * - Search, filter and sort from each header (`FxColumnHeader`), on the
 *   server like every other filter, so they run across the whole list and go
 *   back to page 1.
 * - The header row frozen under the frozen page header.
 * - The pager under the list: 25, 50 or 100 rows, 50 by default (setting
 *   "Rows per page on long lists"), "Showing 51-100 of 12,340"; the page and
 *   filters ride in the address so Back and a shared link return to them.
 * - The list's own Create is the page's red action (`useRegisterMainAction`)
 *   unless the page names another (`config.fx.mainActionId`); toolbar
 *   buttons are icon actions.
 *
 * Slice F3b adds:
 * - the selection bar over the filter bar once a row is ticked
 *   (`FxSelectionBar`): "3 selected", "Select all n" across pages, the bulk
 *   actions as icon actions, Export and ×; floating at the lower edge on
 *   phones;
 * - the empty, nothing-matches, couldn't-load and no-access states
 *   (`FxListState`), smaller inside a record's tab (`fx.compactStates`);
 * - phone cards under 720px (`FxPhoneCards`), the view toggle hidden;
 * - Hold to Copy on the page's copyable columns (`config.fx.copyable`);
 * - the export panel's words (`ExportDialog` with the switch on).
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import type { DragEndEvent } from '@dnd-kit/core';
import { arrayMove, useSortable } from '@dnd-kit/sortable';
import {
  getCoreRowModel,
  useReactTable,
  type Column,
  type ColumnDef,
  type PaginationState,
  type RowSelectionState,
  type SortingState,
  type VisibilityState,
} from '@tanstack/react-table';
import { GripVertical, Info } from 'lucide-react';
import { buildListNav, encodeListQuery } from '@/lib/list-context';
import { cn } from '@/lib/utils';
import { useCan } from '@/hooks/use-can';
import { useDatetime } from '@/hooks/use-datetime';
import { useFxSetting } from '@/hooks/use-fx';
import { useFxListPrefs, type FxColumnsView, type FxListView } from '@/hooks/use-fx-list-prefs';
import { useMediaQuery } from '@/hooks/use-media-query';
import { useResourceList } from '@/hooks/use-resource-list';
import { useImportActivity } from '@/providers/import-activity-provider';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { DataGrid } from '@/components/ui/data-grid';
import { DataGridTableDndRows } from '@/components/ui/data-grid-table-dnd-rows';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Skeleton } from '@/components/ui/skeleton';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { ListSearchInput } from '@/components/platform/list-search-input';
import { PageHeader } from '@/components/platform/page-header';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { SearchSelect } from '@/components/platform/search-select';
import { ExportDialog } from '@/components/platform/resource-list/export-dialog';
import { FilterBuilder } from '@/components/platform/resource-list/filter-builder';
import type { ResourceListProps } from '@/components/platform/resource-list/resource-list';
import type { FxColumnKind } from '@/components/platform/resource-list/types';
import { FxIconAction, FxIconActionButton } from '@/components/fx/actions/icon-action';
import {
  useRegisterMainAction,
  useRegisterOtherActions,
  type FxMainActionSpec,
  type FxOtherActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { FxTooltip } from '@/components/fx/fx-tooltip';
import type { FilterGroup } from '@/types/resource';
import { FxColumnsPanel } from './fx-columns-panel';
import { FxListTable, columnLabel, defId, isStructuralDef } from './fx-list-table';
import { FxListHeaderContext, type FxHeaderKind, type FxListHeaderContextValue } from './header-context';
import {
  combineFilters,
  fxHeaderFilterKind,
  fxStatusColumnIds,
  splitFilters,
  type FxHeaderFilters,
  type FxHeaderValue,
} from './list-logic';
import { FxPager } from './fx-pager';
import { FxListState, fxListStateKind } from './fx-list-state';
import { FxSelectionBar } from './fx-selection-bar';

const NO_OTHERS: FxOtherActionSpec[] = [];
const NO_IDS: string[] = [];

/** Phones show cards (playbook "Responsive": 720px and below). */
export const FX_PHONE_QUERY = '(max-width: 719px)';

/** Same grip as the legacy list's row reorder (rows keep that table). */
function RowDragGrip({ rowId }: { rowId: string }) {
  const { attributes, listeners, setActivatorNodeRef } = useSortable({ id: rowId });
  return (
    <Button
      ref={setActivatorNodeRef}
      type="button"
      variant="ghost"
      mode="icon"
      size="sm"
      aria-label="Drag to reorder"
      onClick={(e) => e.stopPropagation()}
      className="size-7 cursor-grab touch-none text-(--fx-ink-3) active:cursor-grabbing"
      {...attributes}
      {...listeners}
    >
      <GripVertical className="size-4" />
    </Button>
  );
}

const cap = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

function countConditions(group: { rules: unknown[] } | null | undefined): number {
  if (!group) return 0;
  return (group.rules as { kind: string; rules?: unknown[] }[]).reduce(
    (n, r) => n + (r.kind === 'group' ? countConditions(r as { rules: unknown[] }) : 1),
    0,
  );
}

function downloadCsv(filename: string, text: string) {
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const SHORT_KINDS = new Set<FxColumnKind>(['date', 'status', 'number', 'amount']);
const FIELD_KIND: Record<string, FxHeaderKind> = { text: 'text', date: 'date', enum: 'status' };

/** Fixed columns keep their default slots; movable ones follow `order`. */
function fullOrder(defaultOrder: string[], fixed: Set<string>, order: string[]): string[] {
  const movableDefault = defaultOrder.filter((id) => !fixed.has(id));
  const movable = [
    ...order.filter((id) => movableDefault.includes(id)),
    ...movableDefault.filter((id) => !order.includes(id)),
  ];
  let m = 0;
  return defaultOrder.map((id) => (fixed.has(id) ? id : movable[m++]));
}

export function FxResourceList<T extends object>({
  config,
  hideHeader,
  restoreFromCtx,
}: ResourceListProps<T>) {
  const router = useRouter();
  const { can } = useCan();
  const { openImport } = useImportActivity();
  const { timeZone } = useDatetime();

  const pageRows = Number(useFxSetting('page-rows') ?? 50);
  const viewsOn = useFxSetting('views') !== false;
  const columnsOn = useFxSetting('columns') !== false;
  const colDragSetting = useFxSetting('col-drag') !== false;
  const searchOn = useFxSetting('header-search') !== false;
  const freezeOn = useFxSetting('freeze') !== false;
  const sortOn = useFxSetting('header-sort') !== false;

  const restore = restoreFromCtx ?? !hideHeader;
  const list = useResourceList<T>({
    fetcher: config.fetcher,
    defaultSort: config.defaultSort,
    defaultSegment: config.segments ? (config.defaultSegment ?? config.segments[0]?.id) : undefined,
    restoreFromCtx: restore,
    defaultPageSize: pageRows,
  });

  const [rowMenu, setRowMenu] = useState<{ row: T; x: number; y: number; n: number } | null>(null);
  const hasRowActions = config.actions.some((a) => a.surfaces.row);
  const pageCommitted = config.onDeferredCommitted;
  const onDeferredCommitted = useMemo(
    () => (pageCommitted ? (_a: unknown, ids: string[]) => pageCommitted(ids) : undefined),
    [pageCommitted],
  );

  // The page and its filters in the address (playbook "Long lists load in
  // pages"), for every list that owns its page; an embedded list never
  // writes the record's own `ctx`.
  const writeUrl = Boolean(config.urlState) || restore;
  useEffect(() => {
    if (!writeUrl || typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    url.searchParams.set('ctx', encodeListQuery(list.query));
    window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
  }, [writeUrl, list.query]);

  const onFilterChange = config.onFilterChange;
  useEffect(() => {
    onFilterChange?.(list.filter);
  }, [list.filter, onFilterChange]);

  const [rowSelection, setRowSelectionState] = useState<RowSelectionState>({});
  // "Select all n": every match across pages, not only the ticked rows.
  const [allMatching, setAllMatching] = useState(false);
  const setRowSelection = (next: RowSelectionState | ((prev: RowSelectionState) => RowSelectionState)) => {
    setRowSelectionState((prev) => {
      const value = typeof next === 'function' ? next(prev) : next;
      if (Object.values(value).filter(Boolean).length < Object.values(prev).filter(Boolean).length) {
        setAllMatching(false);
      }
      return value;
    });
  };
  const phone = useMediaQuery(FX_PHONE_QUERY);

  const segmentIds = config.segments?.map((s) => s.id).join(' ');
  useEffect(() => {
    if (config.segmentsReady === false) return;
    if (!config.segments || config.segments.length === 0) return;
    if (list.segment && config.segments.some((s) => s.id === list.segment)) return;
    setRowSelection({});
    list.setSegment(config.segments[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- segmentIds is the stable dep for config.segments' identity
  }, [segmentIds, list.segment, config.segmentsReady]);
  // A new search, filter, sort or view is a new set of matches: the ticks go.
  const matchKey = encodeListQuery({ ...list.query, page: 0 });
  const lastMatchKey = useRef(matchKey);
  useEffect(() => {
    if (lastMatchKey.current === matchKey) return;
    lastMatchKey.current = matchKey;
    setRowSelectionState({});
    setAllMatching(false);
  }, [matchKey]);
  const [filterOpen, setFilterOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  // --- header filters and the Filters panel, combined into the one list filter
  const fieldKinds = useMemo(
    () =>
      Object.fromEntries(
        config.filterFields
          .filter((f) => FIELD_KIND[f.type])
          .map((f) => [f.field, FIELD_KIND[f.type]]),
      ),
    [config.filterFields],
  );
  const [filters, setFilters] = useState<{ panel: FilterGroup | null; header: FxHeaderFilters }>(() =>
    splitFilters(list.filter, fieldKinds),
  );
  const firstFilterRun = useRef(true);
  useEffect(() => {
    if (firstFilterRun.current) {
      firstFilterRun.current = false;
      return;
    }
    list.setFilter(combineFilters(filters.panel, filters.header));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- list.setFilter is stable
  }, [filters]);

  // --- view and columns, remembered per list
  const canCard = Boolean(config.cardRender);
  const effectiveColumns = useMemo<ColumnDef<T>[]>(() => {
    if (!config.rowReorder) return config.columns;
    const grip: ColumnDef<T> = {
      id: '__drag',
      header: () => null,
      cell: ({ row }) => (
        <div className="flex justify-center">
          <RowDragGrip rowId={row.id} />
        </div>
      ),
      size: 44,
      enableSorting: false,
      enableResizing: false,
      enableHiding: false,
      meta: { reorderable: false },
    };
    return [grip, ...config.columns];
  }, [config.rowReorder, config.columns]);

  const defaultOrder = useMemo(
    () => effectiveColumns.map((c) => c.id).filter((id): id is string => Boolean(id)),
    [effectiveColumns],
  );

  const prefs = useFxListPrefs(config.viewKey, {
    view: canCard && config.defaultView === 'card' ? 'card' : 'smart',
    columns: { order: [], hidden: [] },
  });
  const storedView: FxListView = prefs.view === 'card' && !canCard ? 'smart' : prefs.view;
  const view: FxListView = viewsOn ? storedView : canCard && storedView === 'card' ? 'card' : 'smart';
  const columnsView: FxColumnsView = view === 'table' ? 'table' : 'smart';
  const viewColumns = prefs.columns[columnsView];

  const sorting: SortingState = list.sort ? [{ id: list.sort.id, desc: list.sort.desc }] : [];
  const pagination: PaginationState = { pageIndex: list.page, pageSize: list.pageSize };
  const showStatusViews = config.enableStatusViews !== false && !config.segments;

  const fixedIds = useMemo(
    () => new Set(effectiveColumns.filter(isStructuralDef).map(defId).filter(Boolean) as string[]),
    [effectiveColumns],
  );
  const columnOrder = useMemo(
    () => fullOrder(defaultOrder, fixedIds, viewColumns.order),
    [defaultOrder, fixedIds, viewColumns.order],
  );
  const columnVisibility = useMemo<VisibilityState>(
    () => Object.fromEntries(viewColumns.hidden.filter((id) => !fixedIds.has(id)).map((id) => [id, false])),
    [viewColumns.hidden, fixedIds],
  );

  const table = useReactTable<T>({
    data: list.data,
    columns: effectiveColumns,
    getRowId: (row) => config.getRowId(row),
    pageCount: Math.max(1, Math.ceil(list.total / list.pageSize)),
    state: { pagination, sorting, rowSelection, columnOrder, columnVisibility },
    manualPagination: true,
    manualSorting: true,
    manualFiltering: true,
    enableRowSelection: true,
    onRowSelectionChange: setRowSelection,
    onPaginationChange: (updater) => {
      const next = typeof updater === 'function' ? updater(pagination) : updater;
      if (next.pageIndex !== list.page) list.setPage(next.pageIndex);
      if (next.pageSize !== list.pageSize) list.setPageSize(next.pageSize);
    },
    onSortingChange: (updater) => {
      const next = typeof updater === 'function' ? updater(sorting) : updater;
      const first = next[0];
      list.setSort(first ? { id: first.id, desc: first.desc } : null);
    },
    meta: {
      resourceCtx: encodeListQuery(list.query),
      pageStartIndex: list.page * list.pageSize,
      reload: list.reload,
    },
    getCoreRowModel: getCoreRowModel(),
  });

  const movableOrder = columnOrder.filter((id) => !fixedIds.has(id));
  const setViewColumns = (order: string[], hidden: string[]) =>
    prefs.setColumns(columnsView, { order, hidden });
  const moveColumn = (activeId: string, overId: string) => {
    const from = movableOrder.indexOf(activeId);
    const to = movableOrder.indexOf(overId);
    if (from < 0 || to < 0) return;
    setViewColumns(arrayMove(movableOrder, from, to), viewColumns.hidden);
  };

  // --- header search, filter and sort
  const kinds = useMemo(() => {
    const sample = (id: string) =>
      list.data.slice(0, 20).map((row) => (row as Record<string, unknown>)[id]);
    return Object.fromEntries(
      defaultOrder.map((id) => [
        id,
        fxHeaderFilterKind(
          config.filterFields.find((f) => f.field === id),
          config.fx?.columnKind?.[id],
          sample(id),
        ),
      ]),
    ) as Record<string, FxHeaderKind | null>;
  }, [defaultOrder, config.filterFields, config.fx?.columnKind, list.data]);

  const shortIds = useMemo(
    () =>
      new Set(
        defaultOrder.filter((id) => {
          const declared = config.fx?.columnKind?.[id];
          if (declared) return SHORT_KINDS.has(declared);
          const field = config.filterFields.find((f) => f.field === id);
          return field?.type === 'date' || field?.type === 'enum' || field?.type === 'bool';
        }),
      ),
    [defaultOrder, config.fx?.columnKind, config.filterFields],
  );

  const copyable = useMemo(() => new Set(config.fx?.copyable ?? []), [config.fx?.copyable]);
  const phoneHidden = useMemo(() => new Set(config.fx?.phoneHidden ?? []), [config.fx?.phoneHidden]);
  const statusIds = useMemo(
    () => fxStatusColumnIds(kinds, config.fx?.columnKind),
    [kinds, config.fx?.columnKind],
  );

  const defaultSort = config.defaultSort ?? null;
  const headerCtx = useMemo<FxListHeaderContextValue>(
    () => ({
      kindOf: (id) => kinds[id] ?? null,
      optionsOf: (id) => config.filterFields.find((f) => f.field === id)?.options ?? [],
      valueOf: (id) => filters.header[id],
      setValue: (id, value: FxHeaderValue | undefined) =>
        setFilters((prev) => {
          const header = { ...prev.header };
          if (value) header[id] = value;
          else delete header[id];
          return { ...prev, header };
        }),
      sort: list.sort,
      cycleSort: (id) => {
        const current = list.sort;
        if (!current || current.id !== id) list.setSort({ id, desc: false });
        else if (!current.desc) list.setSort({ id, desc: true });
        else list.setSort(defaultSort);
      },
      searchOn,
      sortOn,
      timeZone,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- list.setSort is stable
    [kinds, config.filterFields, filters.header, list.sort, defaultSort, searchOn, sortOn, timeZone],
  );

  // --- the frozen page header's height, so the header row sits under it
  const sectionRef = useRef<HTMLElement>(null);
  const [pageHeadH, setPageHeadH] = useState(0);
  useEffect(() => {
    const head = document.querySelector<HTMLElement>('[data-fx-header]');
    if (!head || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => setPageHeadH(Math.ceil(head.getBoundingClientRect().height)));
    ro.observe(head);
    return () => ro.disconnect();
  }, []);

  const changePage = (pageIndex: number) => {
    list.setPage(pageIndex);
    // The list's top goes back under the frozen header; the header row and
    // the columns stay where they are.
    const el = sectionRef.current;
    if (!el) return;
    const head = document.querySelector<HTMLElement>('[data-fx-header]');
    const offset = head ? head.getBoundingClientRect().bottom : 0;
    const top = el.getBoundingClientRect().top;
    if (top < offset) window.scrollBy({ top: top - offset, behavior: 'smooth' });
  };

  // --- rows, navigation, export (as the legacy list)
  const selectedIds = useMemo(() => Object.keys(rowSelection).filter((id) => rowSelection[id]), [rowSelection]);
  const selectedRows = useMemo(
    () => list.data.filter((r) => selectedIds.includes(config.getRowId(r))),
    [list.data, selectedIds, config],
  );

  const ctx = encodeListQuery(list.loadedQuery);
  const rowIndexMap = useMemo(() => {
    const map = new Map<T, number>();
    list.data.forEach((row, i) => map.set(row, i));
    return map;
  }, [list.data]);
  function buildRowHref(row: T, indexOnPage: number): string {
    const href = config.rowHref(row);
    if (!href || href === '#') return href;
    const globalIndex = list.loadedQuery.page * list.loadedQuery.pageSize + indexOnPage;
    return buildListNav(href, { ctx, i: globalIndex, from: config.getRowId(row) });
  }
  const rowHrefFn = config.onRowSelect ? undefined : (row: T) => buildRowHref(row, rowIndexMap.get(row) ?? 0);
  function openRow(row: T) {
    const indexOnPage = rowIndexMap.get(row) ?? 0;
    if (config.onRowSelect) {
      config.onRowSelect(row, indexOnPage, list.data);
      return;
    }
    const href = buildRowHref(row, indexOnPage);
    if (!href || href === '#') return;
    router.push(href);
  }

  function handleRowDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id || !config.rowReorder) return;
    const ids = list.data.map((r) => config.getRowId(r));
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    void config.rowReorder.onReorder(arrayMove(ids, from, to));
  }

  const runtime = { reload: list.reload };
  const filterCount = countConditions(filters.panel);
  const canExport = config.exportColumns.length > 0 && Boolean(config.exporter);

  async function handleExport(columnIds: string[]) {
    if (!config.exporter) return;
    const ids = !allMatching && selectedIds.length ? selectedIds : undefined;
    const csv = await config.exporter(list.query, columnIds, ids);
    downloadCsv(`${config.exportFilename ?? 'export'}.csv`, csv);
    setRowSelection({});
    setAllMatching(false);
  }

  // --- the list's state: nothing yet, nothing matches, couldn't load, no access
  const headerFilterIds = Object.keys(filters.header);
  const filtered = Boolean(list.search.trim()) || filterCount > 0 || headerFilterIds.length > 0;
  const stateKind = fxListStateKind({
    error: list.error,
    errorStatus: list.errorStatus,
    isLoading: list.isLoading,
    rowCount: list.data.length,
    filtered,
  });
  const noun = config.fx?.noun ?? config.pageTitle?.toLowerCase() ?? 'records';
  const onlyHeaderText =
    !list.search.trim() && filterCount === 0 && headerFilterIds.length === 1
      ? filters.header[headerFilterIds[0]]
      : undefined;
  const searchColumn =
    onlyHeaderText?.kind === 'text'
      ? (() => {
          const col = table.getColumn(headerFilterIds[0]);
          return col ? columnLabel(col as Column<unknown, unknown>) : undefined;
        })()
      : undefined;
  const clearFilters = () => {
    list.setSearch('');
    setFilters({ panel: null, header: {} });
  };
  const stateNode: ReactNode = stateKind ? (
    <FxListState
      kind={stateKind}
      compact={Boolean(config.fx?.compactStates)}
      noun={noun}
      title={config.pageTitle ?? cap(noun)}
      canCreate={Boolean(config.onCreate) && (!config.createPermission || can(config.createPermission))}
      trashed={list.statusView === 'trashed'}
      search={list.search.trim() || (onlyHeaderText?.kind === 'text' ? onlyHeaderText.text.trim() : undefined)}
      column={searchColumn}
      onClearFilters={clearFilters}
      onRetry={list.reload}
      onBack={() => router.back()}
    />
  ) : null;

  // --- selection
  const tickedCount = selectedRows.length;
  const selectionCount = allMatching ? list.total : tickedCount;
  // The bar lies over the filter bar (wider screens); what it covers is inert.
  const barOver = selectionCount > 0 && !phone;
  const selectAll = () => {
    setRowSelectionState(Object.fromEntries(list.data.map((r) => [config.getRowId(r), true])));
    if (list.total > list.data.length) setAllMatching(true);
  };

  // --- the red action: the list's own Create, unless the page names another.
  // A list without its own header hands it to the page header only when the
  // page asks (`fx.createInPageHeader`, FX-17).
  const mayCreate = Boolean(config.onCreate) && (!config.createPermission || can(config.createPermission));
  const createIsMain =
    (!hideHeader || config.fx?.createInPageHeader === true) &&
    mayCreate &&
    (config.fx?.mainActionId ?? 'create') === 'create';
  const createLabel = config.createLabel ?? 'Create';
  const fullLabel = config.fx?.fullLabel;
  const onCreate = config.onCreate;
  const mainSpec = useMemo<FxMainActionSpec | null>(
    () =>
      createIsMain && onCreate
        ? {
            id: 'create',
            label: createLabel,
            fullLabel: fullLabel ? fullLabel(selectedRows) : undefined,
            onClick: onCreate,
          }
        : null,
    [createIsMain, onCreate, createLabel, fullLabel, selectedRows],
  );
  useRegisterMainAction(mainSpec);
  // The page's More list (FX-16): header Other Actions named here sit in More.
  useRegisterOtherActions(NO_OTHERS, config.fx?.moreActionIds ?? NO_IDS);

  const listStyle = { '--fx-page-head-h': `${pageHeadH}px` } as CSSProperties;
  const showToggle = viewsOn && !config.rowReorder && !phone;
  const cardView = view === 'card';

  const viewToggle = showToggle && (
    <ToggleGroup
      type="single"
      size="sm"
      value={view}
      onValueChange={(v) => v && prefs.setView(v as FxListView)}
      aria-label="View"
      className="rounded-(--fx-r-pill) border border-(--fx-line-2) bg-(--fx-surface) p-0.5"
    >
      {(['smart', 'table', ...(canCard ? ['card'] : [])] as FxListView[]).map((v) => (
        <ToggleGroupItem
          key={v}
          value={v}
          className="h-8 rounded-(--fx-r-pill) px-3 text-(--fx-ink-2) data-[state=on]:bg-(--fx-link-bg) data-[state=on]:font-semibold data-[state=on]:text-(--fx-link)"
        >
          {v === 'smart' ? 'Smart view' : v === 'table' ? 'Table view' : 'Cards'}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );

  const panelColumns = movableOrder
    .map((id) => table.getColumn(id))
    .filter((c): c is NonNullable<typeof c> => Boolean(c))
    .map((c) => ({ id: c.id, label: columnLabel(c as Column<unknown, unknown>), canHide: c.getCanHide() }));

  return (
    <>
      {!hideHeader && <PageHeader title={config.pageTitle} description={config.pageDescription} />}
      <DataGrid
        table={table}
        recordCount={list.total}
        isLoading={list.isLoading}
        isPlaceholderData={list.isPlaceholderData}
        rowHref={rowHrefFn}
        onRowClick={config.onRowSelect ? openRow : undefined}
        onRowContextMenu={
          hasRowActions
            ? (row, event) =>
                setRowMenu((prev) => ({ row, x: event.clientX, y: event.clientY, n: (prev?.n ?? 0) + 1 }))
            : undefined
        }
        tableLayout={{
          columnsResizable: false,
          columnsMovable: true,
          columnsDraggable: true,
          columnsVisibility: true,
          columnsPinnable: false,
          headerBackground: true,
          rowBorder: true,
        }}
      >
        <section
          ref={sectionRef}
          data-fx-list=""
          style={listStyle}
          className="flex min-w-0 flex-col rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) text-(--fx-ink)"
        >
          <div className="relative flex flex-wrap items-center justify-between gap-3 border-b border-(--fx-line) p-3">
            <div inert={barOver || undefined} className="flex min-w-0 flex-wrap items-center gap-2.5">
              <ListSearchInput
                className="w-64 max-w-full"
                value={list.search}
                onChange={list.setSearch}
                placeholder={config.searchPlaceholder ?? 'Search…'}
                ariaLabel={config.searchPlaceholder ?? 'Search'}
                busy={list.isLoading}
              />
              {config.searchHints && config.searchHints.length > 0 && (
                <HoverCard openDelay={100} closeDelay={50}>
                  <HoverCardTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      mode="icon"
                      className="size-8 text-(--fx-ink-3)"
                      aria-label="What can I search?"
                    >
                      <Info />
                    </Button>
                  </HoverCardTrigger>
                  <HoverCardContent align="start" className="w-64">
                    <p className="mb-1.5 text-xs font-semibold text-(--fx-ink)">You can search by</p>
                    <ul className="flex flex-col gap-1">
                      {config.searchHints.map((hint) => (
                        <li key={hint} className="text-sm text-(--fx-ink-2)">
                          {hint}
                        </li>
                      ))}
                    </ul>
                  </HoverCardContent>
                </HoverCard>
              )}
              {config.segments && (
                <SearchSelect
                  className="w-36"
                  ariaLabel="View segment"
                  options={config.segments.map((s) => ({ label: s.label, value: s.id }))}
                  value={list.segment ?? null}
                  onChange={(v) => {
                    setRowSelection({});
                    list.setSegment(v);
                  }}
                />
              )}
              {showStatusViews && (
                <ToggleGroup
                  type="single"
                  size="sm"
                  value={list.statusView}
                  onValueChange={(v) => {
                    if (!v) return;
                    setRowSelection({});
                    list.setStatusView(v as 'active' | 'trashed');
                  }}
                  className="rounded-(--fx-r-pill) border border-(--fx-line-2) bg-(--fx-surface) p-0.5"
                >
                  {(['active', 'trashed'] as const).map((v) => (
                    <ToggleGroupItem
                      key={v}
                      value={v}
                      className="h-8 rounded-(--fx-r-pill) px-3 text-(--fx-ink-2) data-[state=on]:bg-(--fx-link-bg) data-[state=on]:font-semibold data-[state=on]:text-(--fx-link)"
                    >
                      {v === 'active'
                        ? (config.statusViewLabels?.active ?? 'Active')
                        : (config.statusViewLabels?.trashed ?? 'Trashed')}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
              )}
            </div>

            {selectionCount > 0 && (
              <FxSelectionBar
                count={selectionCount}
                total={list.total}
                allMatching={allMatching}
                onSelectAll={selectAll}
                onClear={() => {
                  setRowSelectionState({});
                  setAllMatching(false);
                }}
                onExport={canExport ? () => setExportOpen(true) : undefined}
                iconFor={config.fx?.iconFor}
                floating={phone}
                actions={config.actions}
                rows={selectedRows}
                runtime={runtime}
                getEntityId={config.getEntityId}
                onDeferredCommitted={config.onDeferredCommitted}
              />
            )}
            <div inert={barOver || undefined} className="flex flex-wrap items-center justify-end gap-2">
              {config.filterFields.length > 0 && (
                <Popover open={filterOpen} onOpenChange={setFilterOpen}>
                  <FxTooltip label="Filters">
                    <PopoverTrigger asChild>
                      <FxIconActionButton
                        label={filterCount > 0 ? `Filters (${filterCount})` : 'Filters'}
                        icon="filter"
                        className={cn(filterCount > 0 && 'border-(--fx-link) text-(--fx-link)')}
                      />
                    </PopoverTrigger>
                  </FxTooltip>
                  <PopoverContent align="end" className="w-auto p-3">
                    <FilterBuilder
                      fields={config.filterFields}
                      initialValue={filters.panel}
                      onApply={(g) => setFilters((prev) => ({ ...prev, panel: g }))}
                      onClose={() => setFilterOpen(false)}
                    />
                  </PopoverContent>
                </Popover>
              )}
              {config.importer && can(config.importer.writePermission) && (
                <FxIconAction
                  label="Import"
                  icon="import"
                  onClick={() =>
                    openImport({ entityType: config.importer!.entityType, context: config.importer!.context })
                  }
                />
              )}
              {canExport && <FxIconAction label="Export" icon="csv-down" onClick={() => setExportOpen(true)} />}
              {mayCreate && !createIsMain && (
                <FxIconAction label={createLabel} icon="add" onClick={config.onCreate} />
              )}
              {viewToggle}
              {columnsOn && !cardView && !phone && (
                <FxColumnsPanel
                  view={columnsView}
                  columns={panelColumns}
                  hidden={viewColumns.hidden}
                  same={prefs.same}
                  onSame={(same) => prefs.setSame(same, columnsView)}
                  onChange={setViewColumns}
                  onReset={() => setViewColumns([], [])}
                />
              )}
            </div>
          </div>

          {cardView ? (
            <div className="p-4">
              {list.isLoading && list.data.length === 0 ? (
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {[0, 1, 2].map((i) => (
                    <div key={i} className="rounded-(--fx-r-l) border border-(--fx-line) p-5">
                      <Skeleton className="size-10 rounded-lg" />
                      <Skeleton className="mt-3 h-5 w-2/5" />
                      <Skeleton className="mt-2 h-4 w-full" />
                    </div>
                  ))}
                </div>
              ) : stateNode ? (
                stateNode
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {list.data.map((row) => {
                    const id = config.getRowId(row);
                    const selected = Boolean(rowSelection[id]);
                    return (
                      <div
                        key={id}
                        role="button"
                        tabIndex={0}
                        onClick={() => openRow(row)}
                        onKeyDown={(e) => e.key === 'Enter' && openRow(row)}
                        data-testid={`resource-card-${id}`}
                        className={cn(
                          'group relative flex flex-col rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) text-left transition-[translate,box-shadow,border-color] duration-(--fx-t-hover) ease-(--fx-ease-out) hover:-translate-y-0.5 hover:shadow-[0_6px_18px_var(--fx-shade)] focus-visible:outline-hidden [:root[data-fx-lift=off]_&]:hover:translate-y-0',
                          selected && 'border-(--fx-link)',
                        )}
                      >
                        <div
                          role="presentation"
                          className="absolute start-3 top-3"
                          onClick={(e) => e.stopPropagation()}
                          onKeyDown={(e) => e.stopPropagation()}
                        >
                          <Checkbox
                            checked={selected}
                            onCheckedChange={(c) => setRowSelection((prev) => ({ ...prev, [id]: Boolean(c) }))}
                            aria-label="Select card"
                          />
                        </div>
                        <div
                          role="presentation"
                          className="absolute end-2 top-2"
                          onClick={(e) => e.stopPropagation()}
                          onKeyDown={(e) => e.stopPropagation()}
                        >
                          <ActionMenu
                            actions={config.actions}
                            rows={[row]}
                            getEntityId={config.getEntityId}
                            runtime={runtime}
                            surface="row"
                            onDeferredCommitted={onDeferredCommitted}
                          />
                        </div>
                        <div className="p-5 pt-10">{config.cardRender!(row)}</div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          ) : config.rowReorder ? (
            // Row reorder lists keep the table they have; their order is the
            // point, so Smart view's moving columns would not help them.
            <div className="relative min-w-0">
              <DataGridTableDndRows
                handleDragEnd={handleRowDragEnd}
                dataIds={list.data.map((r) => config.getRowId(r))}
              />
            </div>
          ) : (
            <FxListHeaderContext.Provider value={headerCtx}>
              <FxListTable
                view={view === 'table' ? 'table' : 'smart'}
                freeze={freezeOn}
                colDrag={columnsOn && colDragSetting}
                shortIds={shortIds}
                rowsKey={ctx}
                onMoveColumn={moveColumn}
                phone={phone}
                copyable={copyable}
                phoneHidden={phoneHidden}
                statusIds={statusIds}
                cardLines={config.fx?.cardLines}
                state={stateNode}
              />
            </FxListHeaderContext.Provider>
          )}

          {!(stateKind && stateKind !== 'no-match') && list.total > 0 && (
            <FxPager
              pageIndex={list.page}
              pageSize={list.pageSize}
              total={list.total}
              onPage={changePage}
              onPageSize={list.setPageSize}
            />
          )}
        </section>

        <ExportDialog
          open={exportOpen}
          onOpenChange={setExportOpen}
          columns={config.exportColumns}
          selectedCount={allMatching ? 0 : selectedIds.length}
          totalCount={list.total}
          onExport={handleExport}
        />
      </DataGrid>
      {rowMenu && (
        <ActionMenu
          key={rowMenu.n}
          defaultOpen
          actions={config.actions}
          rows={[rowMenu.row]}
          getEntityId={config.getEntityId}
          runtime={runtime}
          surface="row"
          onDeferredCommitted={onDeferredCommitted}
          align="start"
          trigger={
            <span
              aria-hidden
              className="pointer-events-none fixed size-0"
              style={{ left: rowMenu.x, top: rowMenu.y }}
            />
          }
        />
      )}
    </>
  );
}

