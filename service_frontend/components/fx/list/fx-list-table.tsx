'use client';

/**
 * The Foundryx UIUX list table (playbook 0.71.0 "Lists"), the switch-on
 * counterpart of `DataGridTableDnd`. It renders inside the same `DataGrid`
 * provider, so every column's own header and cell renderers (tick boxes,
 * action menus, badges) work unchanged.
 *
 * - **Smart view:** each column as wide as its header and values need, up to
 *   320px for long text and 200px for the rest; nothing is ever cut short
 *   with an ellipsis. When the columns don't fit, the right-most move one at
 *   a time into info lines under each row ("Branch : Penang", labels in one
 *   shared width so the colons line up). The row and its info lines hover
 *   and click as one.
 * - **Table view:** every shown column stays; the table slides sideways.
 * - **Frozen header row:** the header row stays pinned under the frozen page
 *   header (setting "Freeze the header row"), on the surface colour with a
 *   soft shadow while stuck, until the table's last rows pass; in Table view
 *   too, following the sideways slider.
 * - **Drag headers to move columns:** a header picks up its column after 6px
 *   of sideways movement (setting "Drag headers to move columns").
 * - **New rows fade in** (0.2 s) when the page, sort or filter changes; the
 *   old ones stay, dimmed, until the new ones arrive.
 * - **Phones** (slice F3b): stacked cards instead of the table
 *   (`FxPhoneCards`); **Hold to Copy** on the page's copyable columns; the
 *   list's empty, nothing-matches and couldn't-load state in place of the
 *   rows, under the header row.
 */
import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from 'react';
import { useRouter } from 'next/navigation';
import {
  closestCenter,
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import { restrictToHorizontalAxis } from '@dnd-kit/modifiers';
import {
  horizontalListSortingStrategy,
  SortableContext,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { flexRender, type Column, type ColumnDef, type Header, type Row } from '@tanstack/react-table';
import { cn } from '@/lib/utils';
import { usePrefetchOnce } from '@/hooks/use-prefetch-once';
import { useDataGrid } from '@/components/ui/data-grid';
import {
  firstDataColumnIndex,
  fromOwnRowControl,
  hasRowHref,
  PrimaryCellLink,
  useRestoreReturnedRow,
  useRowPendingDim,
} from '@/components/ui/data-grid-table';
import { Skeleton } from '@/components/ui/skeleton';
import { FxHoldToCopy } from '@/components/fx/copy/hold-to-copy';
import { FxColumnHeader } from './fx-column-header';
import { FxPhoneCards } from './fx-phone-cards';
import { FX_COLUMN_CAP, planSmartColumns, type FxColumnNeed } from './list-logic';

/** Cell side padding (px-3, both sides). */
const CELL_PAD = 24;
/** Room for the sort arrow in the header's padding. */
const ARROW_ROOM = 12;
/** Width for a tick-box or action column with no declared size. */
const FIXED_FALLBACK = 48;

/** A column definition's id (its own, else its accessor key). */
export function defId<TData>(def: ColumnDef<TData>): string | undefined {
  return def.id ?? (def as { accessorKey?: string }).accessorKey;
}

/** Tick boxes, drag grips and row actions: never hidden, moved or searched. */
export function isStructuralDef<TData>(def: ColumnDef<TData>): boolean {
  const id = defId(def) ?? '';
  if (['select', '__drag', 'actions'].includes(id)) return true;
  const meta = def.meta;
  if (meta?.utility === true) return true;
  return meta?.reorderable === false && !meta?.headerTitle && typeof def.header !== 'string';
}

export function isStructuralColumn<TData>(column: Column<TData, unknown>): boolean {
  return isStructuralDef(column.columnDef);
}

/** The words a column is known by (Columns panel, info lines). */
export function columnLabel<TData>(column: Column<TData, unknown>): string {
  const meta = column.columnDef.meta;
  if (meta?.headerTitle) return meta.headerTitle;
  const header = column.columnDef.header;
  if (typeof header === 'string' && header) return header;
  const words = column.id.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export interface FxListTableProps {
  view: 'smart' | 'table';
  freeze: boolean;
  colDrag: boolean;
  /** Columns whose kind is never long text (dates, statuses, amounts). */
  shortIds: Set<string>;
  /** Changes when a new page, sort or filter's rows arrive (fade-in key). */
  rowsKey: string;
  onMoveColumn: (activeId: string, overId: string) => void;
  /** Phones: stacked cards instead of the table (F3b). */
  phone?: boolean;
  /** Columns whose values Hold to Copy copies (`fx.copyable`). */
  copyable?: Set<string>;
  /** Columns dropped from phone cards (`fx.phoneHidden`). */
  phoneHidden?: Set<string>;
  /** Status-like columns: a phone card's top line shows the first. */
  statusIds?: Set<string>;
  /** Phone card lines (`fx.cardLines`). */
  cardLines?: string[][];
  /** The list's state, shown in place of the rows (F3b). */
  state?: ReactNode;
}

const NONE = new Set<string>();

export function FxListTable({
  view,
  freeze,
  colDrag,
  shortIds,
  rowsKey,
  onMoveColumn,
  phone = false,
  copyable = NONE,
  phoneHidden = NONE,
  statusIds = NONE,
  cardLines,
  state,
}: FxListTableProps) {
  const { table, props, isLoading, isPlaceholderData } = useDataGrid();
  const wrapRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const headRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  useRestoreReturnedRow(bodyRef);
  useRowPendingDim(bodyRef);

  const columns = table.getVisibleLeafColumns();
  const rows = table.getRowModel().rows;
  const columnIds = columns.map((c) => c.id).join(' ');

  // --- measuring: available width and what each column needs
  const [available, setAvailable] = useState(0);
  const [needs, setNeeds] = useState<Record<string, number>>({});

  useEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(([entry]) => setAvailable(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
    // Phone cards and the table are different elements: watch the new one
    // when the list widens past the phone breakpoint (or narrows to it).
  }, [phone]);

  useLayoutEffect(() => {
    const root = measureRef.current;
    if (!root) return;
    const next: Record<string, number> = {};
    root.querySelectorAll<HTMLElement>('[data-fx-measure]').forEach((colEl) => {
      const id = colEl.dataset.fxMeasure as string;
      let max = 0;
      colEl.querySelectorAll<HTMLElement>('[data-fx-measure-item]').forEach((item) => {
        const extra = item.dataset.fxMeasureItem === 'head' ? ARROW_ROOM : 0;
        max = Math.max(max, item.getBoundingClientRect().width + extra);
      });
      next[id] = Math.ceil(max) + CELL_PAD;
    });
    setNeeds((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
    // `phone`: the measuring copy only exists beside the table, so a list
    // first shown as phone cards measures once it widens into a table.
  }, [rowsKey, columnIds, rows.length, phone]);

  // --- the plan: which columns stay, which become info lines, how wide
  const plan = useMemo(() => {
    const cols: FxColumnNeed[] = columns.map((c) => {
      const fixed = isStructuralColumn(c);
      const need = fixed ? (c.columnDef.size ?? FIXED_FALLBACK) : (needs[c.id] ?? 0);
      return { id: c.id, need, fixed, long: !fixed && !shortIds.has(c.id) && need > FX_COLUMN_CAP };
    });
    return planSmartColumns(cols, view === 'smart' ? available : 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- columnIds stands for the column list
  }, [columnIds, needs, available, view, shortIds]);

  const widths = useMemo(() => {
    if (view === 'smart') {
      if (!plan.tooNarrow || available <= 0) return plan.widths;
      // Even two columns don't fit (phones get cards in slice F3b): the
      // columns share the width and their values wrap, so the page never
      // scrolls sideways.
      const sum = Object.values(plan.widths).reduce((a, b) => a + b, 0);
      return Object.fromEntries(
        Object.entries(plan.widths).map(([id, w]) => [id, Math.floor((w * available) / sum)]),
      );
    }
    // Table view: every column at its width; spare width spreads evenly.
    const sum = Object.values(plan.widths).reduce((a, b) => a + b, 0);
    const data = plan.inTable.filter((id) => !isStructuralColumn(table.getColumn(id) as Column<unknown, unknown>));
    const share = available > sum && data.length ? Math.floor((available - sum) / data.length) : 0;
    return Object.fromEntries(
      plan.inTable.map((id) => [id, (plan.widths[id] ?? 0) + (data.includes(id) ? share : 0)]),
    );
  }, [view, plan, available, table]);

  const inTable = useMemo(() => new Set(plan.inTable), [plan]);
  const tableColumns = columns.filter((c) => inTable.has(c.id));
  const infoColumns = view === 'smart' ? columns.filter((c) => plan.infoLines.includes(c.id)) : [];
  const totalWidth = tableColumns.reduce((sum, c) => sum + (widths[c.id] ?? 0), 0);
  const measured = Object.keys(needs).length > 0;
  const tableStyle: CSSProperties | undefined =
    measured && totalWidth > 0 ? { width: `${totalWidth}px` } : undefined;
  const primaryIndex = firstDataColumnIndex(columns);

  // --- frozen header: soft shadow only while stuck; Table view follows the slider
  const [stuck, setStuck] = useState(false);
  useEffect(() => {
    if (!freeze) return;
    const check = () => {
      const head = headRef.current;
      const wrap = wrapRef.current;
      if (!head || !wrap) return;
      const top = parseFloat(getComputedStyle(head).top) || 0;
      setStuck(wrap.getBoundingClientRect().top < top && head.getBoundingClientRect().bottom < wrap.getBoundingClientRect().bottom);
    };
    check();
    window.addEventListener('scroll', check, { passive: true, capture: true });
    return () => window.removeEventListener('scroll', check, { capture: true });
  }, [freeze]);

  const syncHead = () => {
    if (headRef.current && bodyRef.current) headRef.current.scrollLeft = bodyRef.current.scrollLeft;
  };

  const colgroup = (
    <colgroup>
      {tableColumns.map((c) => (
        <col key={c.id} style={measured ? { width: `${widths[c.id] ?? 0}px` } : undefined} />
      ))}
    </colgroup>
  );

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const movableIds = tableColumns.filter((c) => !isStructuralColumn(c)).map((c) => c.id);
  const onDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    onMoveColumn(String(active.id), String(over.id));
  };

  const showSkeleton = isLoading && !isPlaceholderData && rows.length === 0;
  const labelWidth = infoColumns.length
    ? `${Math.max(...infoColumns.map((c) => columnLabel(c).length)) + 2}ch`
    : undefined;

  if (phone) {
    return (
      <div ref={wrapRef} data-fx-list-table="cards" className="relative min-w-0">
        <div ref={bodyRef} data-slot="data-grid-scroller">
          {state ?? (
            <FxPhoneCards
              phoneHidden={phoneHidden}
              copyable={copyable}
              statusIds={statusIds}
              cardLines={cardLines}
            />
          )}
        </div>
      </div>
    );
  }

  return (
    <div ref={wrapRef} data-fx-list-table={view} className="relative min-w-0">
      {/* What each column needs: its header and values at their natural
          width. Hidden, inert and out of the reading order. */}
      <div
        ref={measureRef}
        aria-hidden="true"
        inert
        className="pointer-events-none invisible absolute start-0 top-0 h-0 overflow-hidden"
      >
        {columns
          .filter((c) => !isStructuralColumn(c))
          .map((c) => (
            <div key={c.id} data-fx-measure={c.id}>
              <span data-fx-measure-item="head" className="inline-block w-max text-[0.8125rem] font-semibold">
                {columnLabel(c)}
              </span>
              {rows.map((row) => {
                const cell = row.getAllCells().find((x) => x.column.id === c.id);
                return cell ? (
                  <div key={row.id}>
                    <span data-fx-measure-item="" className="inline-block w-max text-sm">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </span>
                  </div>
                ) : null;
              })}
            </div>
          ))}
      </div>

      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        modifiers={[restrictToHorizontalAxis]}
        onDragEnd={onDragEnd}
      >
        <div
          ref={headRef}
          data-fx-list-head=""
          data-stuck={stuck || undefined}
          className={cn(
            'overflow-hidden border-b border-(--fx-line) bg-(--fx-surface) transition-shadow duration-(--fx-t-hover) ease-(--fx-ease-out)',
            // Frozen right under the frozen page header, wherever it sits:
            // `--fx-head-top` (the shell, css/demos/demo1.css) moves to the
            // very top when the top bar merges into the page header, and the
            // row glides with it; without the shell it is under the top bar.
            freeze &&
              'sticky top-[calc(var(--fx-head-top,calc(var(--header-height,0px)+var(--shell-top-offset,0px)))+var(--fx-page-head-h,0px))] z-(--z-sticky-header) data-[stuck=true]:shadow-[0_8px_14px_-10px_var(--fx-shade)] motion-safe:transition-[top,box-shadow] motion-safe:duration-(--fx-t-layout) motion-safe:ease-(--fx-ease-out)',
          )}
        >
          <table className="w-full table-fixed border-separate border-spacing-0 text-sm" style={tableStyle}>
            {colgroup}
            <thead>
              <tr>
                <SortableContext items={movableIds} strategy={horizontalListSortingStrategy}>
                  {table.getHeaderGroups()[0]?.headers
                    .filter((h) => inTable.has(h.column.id))
                    .map((header) => (
                      <FxHeaderCell
                        key={header.id}
                        header={header}
                        draggable={colDrag && !isStructuralColumn(header.column)}
                      />
                    ))}
                </SortableContext>
              </tr>
            </thead>
          </table>
        </div>
      </DndContext>

      <div
        ref={bodyRef}
        data-slot="data-grid-scroller"
        onScroll={view === 'table' ? syncHead : undefined}
        className={cn(view === 'table' && 'overflow-x-auto overscroll-x-contain')}
      >
        <table
          className={cn(
            'w-full table-fixed border-separate border-spacing-0 text-sm tabular-nums text-(--fx-ink)',
            'transition-opacity duration-(--fx-t-hover) ease-(--fx-ease-out)',
            isPlaceholderData && 'opacity-60',
          )}
          style={tableStyle}
        >
          {colgroup}
          {showSkeleton ? (
            <tbody>
              {Array.from({ length: Math.min(table.getState().pagination?.pageSize ?? 10, 10) }).map((_, i) => (
                <tr key={i}>
                  {tableColumns.map((c) => (
                    <td key={c.id} className="px-3 py-3">
                      {c.columnDef.meta?.skeleton ?? (
                        <Skeleton className="h-4 w-3/4" />
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          ) : state || rows.length === 0 ? (
            <tbody>
              <tr>
                <td colSpan={Math.max(1, tableColumns.length)} className="p-0 text-center text-(--fx-ink-3)">
                  {state ?? <div className="py-6">{props.emptyMessage || 'No data available'}</div>}
                </td>
              </tr>
            </tbody>
          ) : (
            <Fragment key={rowsKey}>
              {rows.map((row) => (
                <FxBodyRow
                  key={row.id}
                  row={row}
                  href={props.rowHref ? props.rowHref(row.original) : undefined}
                  tableColumnIds={inTable}
                  infoColumns={infoColumns}
                  labelWidth={labelWidth}
                  primaryIndex={primaryIndex}
                  copyable={copyable}
                />
              ))}
            </Fragment>
          )}
        </table>
      </div>
    </div>
  );
}

function FxHeaderCell<TData>({
  header,
  draggable,
}: {
  header: Header<TData, unknown>;
  draggable: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: header.column.id,
    disabled: !draggable,
  });
  const def = header.column.columnDef.header;
  const content: ReactNode = header.isPlaceholder ? null : typeof def === 'string' ? (
    <FxColumnHeader column={header.column} title={def} />
  ) : (
    flexRender(def, header.getContext())
  );
  return (
    <th
      ref={setNodeRef}
      data-dragging={isDragging || undefined}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn(
        'group/fxh relative h-10 px-3 text-start align-middle font-normal text-(--fx-ink-2)',
        header.column.columnDef.meta?.fxAlign === 'end' && 'text-end',
        draggable && 'touch-none',
        'data-[dragging=true]:z-(--fx-z-pop) data-[dragging=true]:bg-(--fx-surface) data-[dragging=true]:shadow-[0_6px_18px_var(--fx-shade)]',
        header.column.columnDef.meta?.headerClassName,
      )}
      {...(draggable ? { ...attributes, ...listeners, role: 'columnheader', tabIndex: undefined } : {})}
    >
      {content}
    </th>
  );
}

function FxBodyRow<TData>({
  row,
  href,
  tableColumnIds,
  infoColumns,
  labelWidth,
  primaryIndex,
  copyable,
}: {
  row: Row<TData>;
  href: string | undefined;
  tableColumnIds: Set<string>;
  infoColumns: Column<TData, unknown>[];
  labelWidth: string | undefined;
  primaryIndex: number;
  copyable: Set<string>;
}) {
  const { props, table } = useDataGrid();
  const router = useRouter();
  const prefetchOnce = usePrefetchOnce();
  const mainRowRef = useRef<HTMLTableRowElement>(null);
  const linked = hasRowHref(href);
  const clickable = linked || Boolean(props.onRowClick);
  const selected = Boolean(table.options.enableRowSelection) && row.getIsSelected();

  const open = useCallback(
    (newTab: boolean) => {
      if (!linked) {
        props.onRowClick?.(row.original);
        return;
      }
      if (newTab) window.open(href, '_blank', 'noopener,noreferrer');
      else router.push(href);
    },
    [href, linked, props, router, row.original],
  );

  const onClick = (event: MouseEvent) => {
    if (event.button !== 0 || fromOwnRowControl(event.target)) return;
    open(linked && (event.metaKey || event.ctrlKey || event.shiftKey));
  };
  // Only the row's own keystrokes: Space in a cell's control stays its own.
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.target !== mainRowRef.current) return;
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    open(linked && (event.metaKey || event.ctrlKey || event.shiftKey));
  };
  const onContextMenu = props.onRowContextMenu
    ? (event: MouseEvent) => {
        event.preventDefault();
        props.onRowContextMenu?.(row.original, event);
      }
    : undefined;

  const cells = row.getVisibleCells().filter((c) => tableColumnIds.has(c.column.id));
  const infoCells = infoColumns
    .map((col) => row.getVisibleCells().find((c) => c.column.id === col.id))
    .filter((c): c is NonNullable<typeof c> => Boolean(c));

  const infoList = infoCells.length > 0 && (
    <dl
      className="grid gap-x-2 gap-y-0.5 text-sm"
      style={{ gridTemplateColumns: `${labelWidth ?? 'max-content'} minmax(0, 1fr)` }}
    >
      {infoCells.map((cell) => (
        <Fragment key={cell.id}>
          <dt className="text-xs leading-5 text-(--fx-ink-3)">{columnLabel(cell.column)} :</dt>
          <dd className="min-w-0 break-words text-start text-(--fx-ink)">
            {copyable.has(cell.column.id) ? (
              <FxHoldToCopy>{flexRender(cell.column.columnDef.cell, cell.getContext())}</FxHoldToCopy>
            ) : (
              flexRender(cell.column.columnDef.cell, cell.getContext())
            )}
          </dd>
        </Fragment>
      ))}
    </dl>
  );

  return (
    <tbody
      data-row-id={row.id}
      data-state={selected ? 'selected' : undefined}
      onClick={clickable ? onClick : undefined}
      onAuxClick={
        linked
          ? (event) => {
              if (event.button !== 1 || fromOwnRowControl(event.target)) return;
              event.preventDefault();
              open(true);
            }
          : undefined
      }
      onKeyDown={clickable ? onKeyDown : undefined}
      onContextMenu={onContextMenu}
      onPointerEnter={linked ? () => prefetchOnce(href) : undefined}
      className={cn(
        'group/row animate-in fade-in duration-(--fx-t-hover) ease-(--fx-ease-out)',
        'transition-[opacity] data-[pending=true]:opacity-50',
        clickable && 'cursor-pointer',
        '[&>tr>td]:transition-[background-color] [&>tr>td]:duration-(--fx-t-hover) [&>tr>td]:ease-(--fx-ease-out)',
        'hover:[&>tr>td]:bg-(--fx-surface-2) data-[state=selected]:[&>tr>td]:bg-(--fx-link-bg) data-[returned=true]:[&>tr>td]:bg-(--fx-link-bg)',
        '[&>tr:last-child>td]:border-b [&>tr:last-child>td]:border-(--fx-line)',
      )}
    >
      <tr
        ref={mainRowRef}
        tabIndex={clickable ? 0 : undefined}
        className="focus-visible:outline-hidden focus-visible:[&>td]:shadow-[inset_0_2px_0_var(--fx-link),inset_0_-2px_0_var(--fx-link)]"
      >
        {cells.map((cell) => {
          const rendered = flexRender(cell.column.columnDef.cell, cell.getContext());
          const content = copyable.has(cell.column.id) ? <FxHoldToCopy>{rendered}</FxHoldToCopy> : rendered;
          const isPrimary = cell.column.getIndex() === primaryIndex;
          return (
            <td
              key={cell.id}
              className={cn(
                'relative break-words px-3 align-middle',
                cell.column.columnDef.meta?.fxAlign === 'end' && 'text-end tabular-nums',
                infoCells.length ? 'pt-3 pb-1' : 'py-3',
                cell.column.columnDef.meta?.cellClassName,
              )}
            >
              {isPrimary && linked ? <PrimaryCellLink href={href}>{content}</PrimaryCellLink> : content}
            </td>
          );
        })}
      </tr>
      {infoCells.length > 0 && (
        <tr data-fx-info-lines="">
          <td colSpan={cells.length} className="px-3 pb-3">
            {infoList}
          </td>
        </tr>
      )}
    </tbody>
  );
}
