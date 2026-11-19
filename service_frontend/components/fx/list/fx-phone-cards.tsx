'use client';

/**
 * Phone cards (playbook 0.71.0 "Lists > Phones: stacked cards always").
 *
 * Under 720px a Foundryx UIUX list shows one card per row instead of the
 * table, and the view toggle hides. Each card is the row's own cells:
 * - the top line holds what it is (the first data column) and its status;
 * - then the page's `fx.cardLines`, or every other shown column as an info
 *   line ("Branch : Penang", labels in one width so the colons line up); an
 *   amount column (`meta.fxAlign: 'end'`) in a card line sits at its end;
 * - cells marked phone-hidden (`fx.phoneHidden`) are dropped;
 * - the tick box sits at the card's start, the row's action menu at its end.
 *
 * The card opens the row like a table row does, and carries `data-row-id`,
 * so coming back to the list tints the card you opened.
 */
import { Fragment, useCallback, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import { flexRender, type Cell, type Row } from '@tanstack/react-table';
import { cn } from '@/lib/utils';
import { useDataGrid } from '@/components/ui/data-grid';
import { firstDataColumnIndex, fromOwnRowControl, hasRowHref } from '@/components/ui/data-grid-table';
import { Skeleton } from '@/components/ui/skeleton';
import { FxHoldToCopy } from '@/components/fx/copy/hold-to-copy';
import { columnLabel, isStructuralColumn } from './fx-list-table';

export interface FxPhoneCardsProps {
  phoneHidden: Set<string>;
  copyable: Set<string>;
  statusIds: Set<string>;
  cardLines?: string[][];
  /** Shown instead of the cards when there are none (the list's state). */
  emptyState?: ReactNode;
}

/** Which cells go where on a card (pure, for tests). */
export function fxCardLayout(
  columnIds: string[],
  opts: {
    primaryId: string | undefined;
    structural: Set<string>;
    phoneHidden: Set<string>;
    statusIds: Set<string>;
    cardLines?: string[][];
  },
): { top: string[]; status: string[]; lines: string[][]; info: string[] } {
  const shown = columnIds.filter((id) => !opts.structural.has(id) && !opts.phoneHidden.has(id));
  const top = opts.primaryId && shown.includes(opts.primaryId) ? [opts.primaryId] : shown.slice(0, 1);
  const status = shown.filter((id) => opts.statusIds.has(id) && !top.includes(id)).slice(0, 1);
  const used = new Set([...top, ...status]);
  if (opts.cardLines?.length) {
    const lines = opts.cardLines
      .map((line) => line.filter((id) => shown.includes(id) && !used.has(id)))
      .filter((line) => line.length > 0);
    return { top, status, lines, info: [] };
  }
  return { top, status, lines: [], info: shown.filter((id) => !used.has(id)) };
}

export function FxPhoneCards({ phoneHidden, copyable, statusIds, cardLines, emptyState }: FxPhoneCardsProps) {
  const { table, isLoading, isPlaceholderData } = useDataGrid();
  const rows = table.getRowModel().rows;
  const columns = table.getVisibleLeafColumns();
  const primaryIdx = firstDataColumnIndex(columns);
  const structural = new Set(columns.filter((c) => isStructuralColumn(c)).map((c) => c.id));
  const layout = fxCardLayout(
    columns.map((c) => c.id),
    { primaryId: columns[primaryIdx]?.id, structural, phoneHidden, statusIds, cardLines },
  );
  const labelWidth = layout.info.length
    ? `${Math.max(...layout.info.map((id) => columnLabel(table.getColumn(id)!).length)) + 2}ch`
    : undefined;

  if (isLoading && !isPlaceholderData && rows.length === 0) {
    return (
      <div className="flex flex-col gap-3 p-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="rounded-(--fx-r-l) border border-(--fx-line) p-4">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="mt-2 h-3 w-3/4" />
          </div>
        ))}
      </div>
    );
  }
  if (rows.length === 0) return <>{emptyState}</>;

  return (
    <ul
      data-fx-phone-cards=""
      className={cn(
        'flex flex-col gap-3 p-3 transition-opacity duration-(--fx-t-hover) ease-(--fx-ease-out)',
        isPlaceholderData && 'opacity-60',
      )}
    >
      {rows.map((row) => (
        <FxPhoneCard
          key={row.id}
          row={row}
          layout={layout}
          structural={structural}
          copyable={copyable}
          labelWidth={labelWidth}
        />
      ))}
    </ul>
  );
}

function FxPhoneCard<TData>({
  row,
  layout,
  structural,
  copyable,
  labelWidth,
}: {
  row: Row<TData>;
  layout: ReturnType<typeof fxCardLayout>;
  structural: Set<string>;
  copyable: Set<string>;
  labelWidth: string | undefined;
}) {
  const { props, table } = useDataGrid();
  const router = useRouter();
  const href = props.rowHref ? props.rowHref(row.original) : undefined;
  const linked = hasRowHref(href);
  const clickable = linked || Boolean(props.onRowClick);
  const selected = Boolean(table.options.enableRowSelection) && row.getIsSelected();
  const cells = row.getVisibleCells();
  const byId = (id: string) => cells.find((c) => c.column.id === id);

  const open = useCallback(() => {
    if (linked) router.push(href);
    else props.onRowClick?.(row.original);
  }, [href, linked, props, router, row.original]);

  const value = (cell: Cell<TData, unknown> | undefined) => {
    if (!cell) return null;
    const content = flexRender(cell.column.columnDef.cell, cell.getContext());
    return copyable.has(cell.column.id) ? <FxHoldToCopy>{content}</FxHoldToCopy> : content;
  };

  const onClick = (event: MouseEvent) => {
    if (event.button !== 0 || fromOwnRowControl(event.target)) return;
    open();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLLIElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    open();
  };

  const select = byId('select');
  const tail = cells.filter((c) => structural.has(c.column.id) && c.column.id !== 'select');

  return (
    <li
      data-row-id={row.id}
      data-state={selected ? 'selected' : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={clickable ? onClick : undefined}
      onKeyDown={clickable ? onKeyDown : undefined}
      className={cn(
        'relative flex gap-3 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-4 text-sm text-(--fx-ink)',
        'animate-in fade-in duration-(--fx-t-hover) ease-(--fx-ease-out) transition-[background-color,opacity]',
        'data-[pending=true]:opacity-50 data-[returned=true]:bg-(--fx-link-bg) data-[state=selected]:border-(--fx-link) data-[state=selected]:bg-(--fx-link-bg)',
        clickable && 'cursor-pointer',
      )}
    >
      {select && <div className="pt-0.5">{flexRender(select.column.columnDef.cell, select.getContext())}</div>}
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 break-words font-semibold">{value(byId(layout.top[0] ?? ''))}</div>
          {layout.status[0] && <div className="shrink-0">{value(byId(layout.status[0]))}</div>}
        </div>
        {layout.lines.map((line, i) => (
          <div key={i} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-(--fx-ink-2)">
            {line.map((id) => (
              <span
                key={id}
                className={cn(
                  'min-w-0 break-words',
                  // An amount (`meta.fxAlign: 'end'`) closes its line at the
                  // card's end, as in the table's right-aligned column.
                  byId(id)?.column.columnDef.meta?.fxAlign === 'end' && 'ms-auto text-end tabular-nums',
                )}
              >
                {value(byId(id))}
              </span>
            ))}
          </div>
        ))}
        {layout.info.length > 0 && (
          <dl
            className="grid gap-x-2 gap-y-0.5"
            style={{ gridTemplateColumns: `${labelWidth ?? 'max-content'} minmax(0, 1fr)` }}
          >
            {layout.info.map((id) => {
              const cell = byId(id);
              if (!cell) return null;
              return (
                <Fragment key={id}>
                  <dt className="text-xs leading-5 text-(--fx-ink-3)">{columnLabel(cell.column)} :</dt>
                  <dd className="min-w-0 break-words">{value(cell)}</dd>
                </Fragment>
              );
            })}
          </dl>
        )}
      </div>
      {tail.map((cell) => (
        <div key={cell.id} className="-me-2 -mt-2 shrink-0">
          {flexRender(cell.column.columnDef.cell, cell.getContext())}
        </div>
      ))}
    </li>
  );
}
