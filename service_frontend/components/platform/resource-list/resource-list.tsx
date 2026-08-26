'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type PaginationState,
  type RowSelectionState,
  type SortingState,
} from '@tanstack/react-table';
import type { DragEndEvent } from '@dnd-kit/core';
import { arrayMove, useSortable } from '@dnd-kit/sortable';
import { Columns3, Download, Filter, GripVertical, Info, LayoutGrid, List, Plus, Search, Upload, X } from 'lucide-react';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';
import { cn } from '@/lib/utils';
import { encodeListQuery } from '@/lib/list-context';
import { useResourceList } from '@/hooks/use-resource-list';
import { useViewPreferences } from '@/hooks/use-view-preferences';
import { useCan } from '@/hooks/use-can';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardFooter,
  CardHeader,
  CardHeading,
  CardTable,
  CardToolbar,
} from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Skeleton } from '@/components/ui/skeleton';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { DataGrid } from '@/components/ui/data-grid';
import { DataGridColumnVisibility } from '@/components/ui/data-grid-column-visibility';
import { DataGridPagination } from '@/components/ui/data-grid-pagination';
import { DataGridTableDnd } from '@/components/ui/data-grid-table-dnd';
import { DataGridTableDndRows } from '@/components/ui/data-grid-table-dnd-rows';
import { Input } from '@/components/ui/input';
import { SearchSelect } from '@/components/platform/search-select';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Badge } from '@/components/ui/badge';
import { BulkActions } from '@/components/platform/resource-actions/bulk-actions';
import { FilterBuilder } from './filter-builder';
import { ExportDialog } from './export-dialog';
import type { ResourceListConfig } from './types';
import { useImportActivity } from '@/providers/import-activity-provider';

/**
 * Row drag handle - a plain muted GripVertical (matches the triage board's card
 * grip so the two surfaces read consistently, per UX feedback). Grabs the same
 * `useSortable(id)` listeners the DndRows body wires up.
 */
function RowDragGrip({ rowId }: { rowId: string }) {
  const { attributes, listeners, setActivatorNodeRef } = useSortable({ id: rowId });
  return (
    <button
      type="button"
      ref={setActivatorNodeRef}
      aria-label="Drag to reorder"
      onClick={(e) => e.stopPropagation()}
      className="flex cursor-grab touch-none items-center text-muted-foreground/60 hover:text-foreground active:cursor-grabbing"
      {...attributes}
      {...listeners}
    >
      <GripVertical className="size-4" />
    </button>
  );
}

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

export interface ResourceListProps<T extends object> {
  config: ResourceListConfig<T>;
}

/**
 * The system-wide list view. Driven by a per-entity config (plan 02 §3a):
 * server-side search/filter/sort/paginate, resizable + reorderable + hideable
 * columns persisted per user, row-click into the form (carrying record-nav
 * ctx), bulk actions, and CSV export.
 */
export function ResourceList<T extends object>({ config }: ResourceListProps<T>) {
  const router = useRouter();
  const { can } = useCan();
  const { openImport } = useImportActivity();
  const list = useResourceList<T>({
    fetcher: config.fetcher,
    defaultSort: config.defaultSort,
    defaultSegment: config.segments ? (config.defaultSegment ?? config.segments[0]?.id) : undefined,
  });
  const prefs = useViewPreferences(config.viewKey);

  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [filterOpen, setFilterOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  // Card/list view - only offered when the config supplies a card renderer.
  // Persisted per user per list in localStorage (no backend column-prefs change).
  const canCard = Boolean(config.cardRender);
  const viewStorageKey = `resource-view:${config.viewKey}`;
  const [view, setView] = useState<'card' | 'list'>('list');
  useEffect(() => {
    if (!canCard) return;
    const saved = typeof window !== 'undefined' ? window.localStorage.getItem(viewStorageKey) : null;
    setView(saved === 'card' || saved === 'list' ? saved : config.defaultView ?? 'list');
  }, [canCard, viewStorageKey, config.defaultView]);
  const changeView = (v: 'card' | 'list') => {
    setView(v);
    if (typeof window !== 'undefined') window.localStorage.setItem(viewStorageKey, v);
  };
  const cardView = canCard && view === 'card';

  const sorting: SortingState = list.sort ? [{ id: list.sort.id, desc: list.sort.desc }] : [];
  const pagination: PaginationState = { pageIndex: list.page, pageSize: list.pageSize };
  // N-way segments replace the binary status views when configured.
  const showStatusViews = config.enableStatusViews !== false && !config.segments;

  // Opt-in row drag-to-reorder: prepend a fixed left grip column and swap the
  // table body renderer (below). Existing lists (no rowReorder) are unaffected.
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

  function handleRowDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id || !config.rowReorder) return;
    const ids = list.data.map((r) => config.getRowId(r));
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    void config.rowReorder.onReorder(arrayMove(ids, from, to));
  }

  // Column order: saved prefs, else the config's declared order. Required for
  // both drag-reorder and the header "move" actions to have a baseline.
  const defaultColumnOrder = useMemo(
    () => effectiveColumns.map((c) => c.id).filter((id): id is string => Boolean(id)),
    [effectiveColumns],
  );
  // Columns that can't be reordered (e.g. select, actions) stay pinned at their
  // default slot regardless of drags.
  const fixedIds = useMemo(
    () =>
      new Set(
        effectiveColumns.filter((c) => c.meta?.reorderable === false).map((c) => c.id as string),
      ),
    [effectiveColumns],
  );
  // Normalize: fixed columns always sit at their default slots; movable columns
  // follow the saved order (new columns appended). Self-heals any stale prefs
  // where a fixed column had drifted.
  const columnOrder = useMemo(() => {
    const raw = prefs.columnOrder.length ? prefs.columnOrder : defaultColumnOrder;
    const movableDefault = defaultColumnOrder.filter((id) => !fixedIds.has(id));
    const movableOrdered = [
      ...raw.filter((id) => !fixedIds.has(id) && movableDefault.includes(id)),
      ...movableDefault.filter((id) => !raw.includes(id)),
    ];
    let m = 0;
    return defaultColumnOrder.map((id) => (fixedIds.has(id) ? id : movableOrdered[m++]));
  }, [prefs.columnOrder, defaultColumnOrder, fixedIds]);

  function handleColumnDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    // Reorder only the movable subset, then rebuild the full order with fixed
    // columns held at their default positions - so select/actions never drift.
    const movable = columnOrder.filter((id) => !fixedIds.has(id));
    const from = movable.indexOf(String(active.id));
    const to = movable.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    const reordered = arrayMove(movable, from, to);

    let m = 0;
    const next = defaultColumnOrder.map((id) => (fixedIds.has(id) ? id : reordered[m++]));
    prefs.setColumnOrder(next);
  }

  const table = useReactTable<T>({
    data: list.data,
    columns: effectiveColumns,
    getRowId: (row) => config.getRowId(row),
    pageCount: Math.max(1, Math.ceil(list.total / list.pageSize)),
    state: {
      pagination,
      sorting,
      rowSelection,
      columnOrder,
      columnVisibility: prefs.columnVisibility,
      columnSizing: prefs.columnSizing,
    },
    manualPagination: true,
    manualSorting: true,
    manualFiltering: true,
    columnResizeMode: 'onChange',
    enableRowSelection: true,
    onRowSelectionChange: setRowSelection,
    onColumnOrderChange: prefs.setColumnOrder,
    onColumnVisibilityChange: prefs.setColumnVisibility,
    onColumnSizingChange: prefs.setColumnSizing,
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

  const selectedIds = useMemo(
    () => Object.keys(rowSelection).filter((id) => rowSelection[id]),
    [rowSelection],
  );
  const selectedRows = useMemo(
    () => list.data.filter((r) => selectedIds.includes(config.getRowId(r))),
    [list.data, selectedIds, config],
  );

  const ctx = encodeListQuery(list.query);
  function openRow(row: T) {
    const indexOnPage = list.data.indexOf(row);
    // Inline master-detail (form-in-form): open in place instead of navigating.
    if (config.onRowSelect) {
      config.onRowSelect(row, indexOnPage, list.data);
      return;
    }
    const href = config.rowHref(row);
    // A config without a detail page returns '#'/'' → the row/card doesn't navigate.
    if (!href || href === '#') return;
    const globalIndex = list.page * list.pageSize + indexOnPage;
    router.push(`${href}?ctx=${ctx}&i=${globalIndex}`);
  }

  const runtime = { reload: list.reload };
  const filterCount = countConditions(list.filter);

  async function handleExport(columnIds: string[]) {
    const csv = await config.exporter(list.query, columnIds, selectedIds.length ? selectedIds : undefined);
    downloadCsv(`${config.exportFilename ?? 'export'}.csv`, csv);
    setRowSelection({});
  }

  return (
    <DataGrid
      table={table}
      recordCount={list.total}
      isLoading={list.isLoading}
      onRowClick={openRow}
      tableLayout={{
        columnsResizable: true,
        columnsMovable: true,
        columnsDraggable: true,
        columnsVisibility: true,
        columnsPinnable: true,
        headerBackground: true,
        rowBorder: true,
      }}
    >
      <Card>
        <CardHeader className="flex-wrap gap-3 py-4">
          <CardHeading>
            <div className="flex flex-wrap items-center gap-2.5">
              <div className="relative">
                <Search className="absolute start-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
                <Input
                  className="ps-9 w-64"
                  placeholder={config.searchPlaceholder ?? 'Search…'}
                  value={list.search}
                  onChange={(e) => list.setSearch(e.target.value)}
                />
                {list.search && (
                  <Button
                    variant="ghost"
                    size="sm"
                    mode="icon"
                    className="absolute end-1 top-1/2 -translate-y-1/2 size-7"
                    onClick={() => list.setSearch('')}
                    aria-label="Clear search"
                  >
                    <X />
                  </Button>
                )}
              </div>

              {config.searchHints && config.searchHints.length > 0 && (
                <HoverCard openDelay={100} closeDelay={50}>
                  <HoverCardTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      mode="icon"
                      className="size-8 text-muted-foreground"
                      aria-label="What can I search?"
                    >
                      <Info />
                    </Button>
                  </HoverCardTrigger>
                  <HoverCardContent align="start" className="w-64">
                    <p className="mb-1.5 text-xs font-semibold text-foreground">You can search by</p>
                    <ul className="flex flex-col gap-1">
                      {config.searchHints.map((hint) => (
                        <li key={hint} className="flex items-center gap-2 text-sm text-muted-foreground">
                          <span className="size-1 rounded-full bg-muted-foreground/60" />
                          {hint}
                        </li>
                      ))}
                    </ul>
                  </HoverCardContent>
                </HoverCard>
              )}

              {config.segments && (
                /* Dropdown, not a toggle row - segment sets grow (user
                   feedback: a long status list would stretch the toolbar). */
                <SearchSelect
                  className="w-36"
                  ariaLabel="View segment"
                  options={config.segments.map((s) => ({ label: s.label, value: s.id }))}
                  value={list.segment ?? null}
                  onChange={(v) => {
                    // Same invariant as status views: selection belongs to the
                    // segment it was made in.
                    setRowSelection({});
                    list.setSegment(v);
                  }}
                />
              )}

              {showStatusViews && (
                <ToggleGroup
                  type="single"
                  size="sm"
                  variant="outline"
                  value={list.statusView}
                  onValueChange={(v) => {
                    if (!v) return;
                    // Selection belongs to the view it was made in - carrying it
                    // across views silently exports/acts on rows the user can no
                    // longer see (review finding: cross-view export dropped rows).
                    setRowSelection({});
                    list.setStatusView(v as 'active' | 'trashed');
                  }}
                >
                  {/* Selected segment is filled primary - the default bg-accent
                      "on" state was too subtle to read which view is active. */}
                  <ToggleGroupItem
                    value="active"
                    className="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:border-primary"
                  >
                    {config.statusViewLabels?.active ?? 'Active'}
                  </ToggleGroupItem>
                  <ToggleGroupItem
                    value="trashed"
                    className="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:border-primary"
                  >
                    {config.statusViewLabels?.trashed ?? 'Trashed'}
                  </ToggleGroupItem>
                </ToggleGroup>
              )}

              {canCard && (
                <ToggleGroup
                  type="single"
                  size="sm"
                  variant="outline"
                  value={view}
                  onValueChange={(v) => v && changeView(v as 'card' | 'list')}
                  aria-label="View mode"
                >
                  <ToggleGroupItem
                    value="card"
                    aria-label="Card view"
                    className="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:border-primary"
                  >
                    <LayoutGrid />
                  </ToggleGroupItem>
                  <ToggleGroupItem
                    value="list"
                    aria-label="List view"
                    className="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:border-primary"
                  >
                    <List />
                  </ToggleGroupItem>
                </ToggleGroup>
              )}
            </div>
          </CardHeading>

          <CardToolbar>
            {selectedRows.length > 0 ? (
              <div className="flex flex-wrap items-center justify-end gap-2">
                <span className="text-sm text-muted-foreground">
                  {selectedRows.length} selected
                </span>
                <BulkActions actions={config.actions} rows={selectedRows} runtime={runtime} />
                <Button variant="outline" size="sm" onClick={() => setExportOpen(true)}>
                  <Upload /> Export
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setRowSelection({})}
                  aria-label="Clear selection"
                >
                  <X /> Clear
                </Button>
              </div>
            ) : (
              <div className="flex flex-wrap items-center justify-end gap-2">
                {config.filterFields.length > 0 && (
                  <Popover open={filterOpen} onOpenChange={setFilterOpen}>
                    <PopoverTrigger asChild>
                      <Button variant="outline" size="sm">
                        <Filter />
                        Filters
                        {filterCount > 0 && (
                          <Badge variant="primary" size="sm" shape="circle">
                            {filterCount}
                          </Badge>
                        )}
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent align="end" className="w-auto p-3">
                      <FilterBuilder
                        fields={config.filterFields}
                        onApply={(g) => list.setFilter(g)}
                        onClose={() => setFilterOpen(false)}
                      />
                    </PopoverContent>
                  </Popover>
                )}

                {config.importer && can(config.importer.writePermission) && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      openImport({
                        entityType: config.importer!.entityType,
                        context: config.importer!.context,
                      })
                    }
                  >
                    <Download />
                    Import
                  </Button>
                )}

                <Button variant="outline" size="sm" onClick={() => setExportOpen(true)}>
                  <Upload />
                  Export
                </Button>

                {!cardView && (
                  <DataGridColumnVisibility
                    table={table}
                    trigger={
                      <Button variant="outline" size="sm">
                        <Columns3 />
                        Columns
                      </Button>
                    }
                  />
                )}

                {config.onCreate && (!config.createPermission || can(config.createPermission)) && (
                  <Button variant="primary" size="sm" onClick={config.onCreate}>
                    <Plus />
                    {config.createLabel ?? 'Create'}
                  </Button>
                )}
              </div>
            )}
          </CardToolbar>
        </CardHeader>

        {cardView ? (
          <div className="p-4">
            {list.isLoading ? (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="rounded-lg border p-5">
                    <Skeleton className="size-10 rounded-lg" />
                    <Skeleton className="mt-3 h-5 w-2/5" />
                    <Skeleton className="mt-2 h-4 w-full" />
                  </div>
                ))}
              </div>
            ) : list.data.length === 0 ? (
              <div className="py-16 text-center text-sm text-muted-foreground">No records</div>
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
                        'group relative flex flex-col rounded-lg border bg-card text-left transition-colors hover:border-primary/40 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring',
                        selected && 'border-primary ring-1 ring-primary',
                      )}
                    >
                      <div className="absolute start-3 top-3 z-10" onClick={(e) => e.stopPropagation()}>
                        <Checkbox
                          checked={selected}
                          onCheckedChange={(c) =>
                            setRowSelection((prev) => ({ ...prev, [id]: Boolean(c) }))
                          }
                          aria-label="Select card"
                        />
                      </div>
                      <div className="absolute end-2 top-2 z-10" onClick={(e) => e.stopPropagation()}>
                        <ActionMenu actions={config.actions} rows={[row]} runtime={runtime} surface="row" />
                      </div>
                      <div className="p-5 pt-10">{config.cardRender!(row)}</div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ) : (
          <CardTable>
            <ScrollArea>
              {config.rowReorder ? (
                <DataGridTableDndRows
                  handleDragEnd={handleRowDragEnd}
                  dataIds={list.data.map((r) => config.getRowId(r))}
                />
              ) : (
                <DataGridTableDnd handleDragEnd={handleColumnDragEnd} />
              )}
              <ScrollBar orientation="horizontal" />
            </ScrollArea>
          </CardTable>
        )}

        <CardFooter className={cn('justify-center md:justify-between flex-col md:flex-row gap-3')}>
          <DataGridPagination sizes={[10, 25, 50, 100]} />
        </CardFooter>
      </Card>

      <ExportDialog
        open={exportOpen}
        onOpenChange={setExportOpen}
        columns={config.exportColumns}
        selectedCount={selectedIds.length}
        onExport={handleExport}
      />
    </DataGrid>
  );
}
