'use client';

import * as React from 'react';
import { CSSProperties, Fragment, ReactNode, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { Checkbox } from '@/components/ui/checkbox';
import { useDataGrid } from '@/components/ui/data-grid';
import { Cell, Column, flexRender, Header, HeaderGroup, Row, Table } from '@tanstack/react-table';
import { cva } from 'class-variance-authority';
import { cn } from '@/lib/utils';
import { useHorizontalOverflow } from '@/hooks/use-horizontal-overflow';
import { usePrefetchOnce } from '@/hooks/use-prefetch-once';

const headerCellSpacingVariants = cva('', {
  variants: {
    size: {
      dense: 'px-2.5 h-8',
      default: 'px-4',
    },
  },
  defaultVariants: {
    size: 'default',
  },
});

const bodyCellSpacingVariants = cva('', {
  variants: {
    size: {
      dense: 'px-2.5 py-2',
      default: 'px-4 py-3',
    },
  },
  defaultVariants: {
    size: 'default',
  },
});

function getPinningStyles<TData>(column: Column<TData>): CSSProperties {
  const isPinned = column.getIsPinned();

  return {
    left: isPinned === 'left' ? `${column.getStart('left')}px` : undefined,
    right: isPinned === 'right' ? `${column.getAfter('right')}px` : undefined,
    position: isPinned ? 'sticky' : 'relative',
    width: column.getSize(),
    zIndex: isPinned ? 1 : 0,
  };
}

/**
 * The index of the first leaf column that is real record DATA - not a
 * selection checkbox, a drag handle, or any other structural column
 * (AC-DLA-13's mobile pin, fix round 1: generalised past the original
 * `select`-only check). A column is skipped when its id is `select` or
 * `__drag` (the two structural ids this shell mints itself), OR its meta
 * marks it `reorderable: false` (the existing convention EVERY fixed/action
 * column in the app already sets) OR `utility: true`. Returns -1 (never
 * matches a real column index) if every leaf column is structural.
 */
function firstDataColumnIndex<TData>(leafColumns: Column<TData>[]): number {
  return leafColumns.findIndex((column) => {
    if (column.id === 'select' || column.id === '__drag') return false;
    const meta = column.columnDef.meta;
    if (meta?.reorderable === false) return false;
    if (meta?.utility === true) return false;
    return true;
  });
}

/**
 * Under `sm`, the first non-select column pins to the start edge while the
 * rest of the row scrolls sideways underneath it (AC-DLA-13) - a purely
 * CSS/viewport-driven pin, independent of TanStack's `columnsPinnable` state
 * (which stays a desktop, explicitly-opted-in feature).
 */
// `!` (important) on every declaration: a plain `.relative` utility class -
// header/body cells already carry one, and the row-select stripe compound
// selector `[&_>:first-child]:relative>:first-child` outranks a bare class by
// specificity too - would otherwise win the `position` property over this
// (same-specificity) responsive variant regardless of source order.
//
// Split head/body (fix round 1, AC-DLA-13): the pinned cell must never
// differ in colour from the rest of its row, so its background follows the
// SAME hover/selected/striped conditions the row itself carries - via
// `group-*:` variants keyed off `group` on the `<tr>` (DataGridTableHeadRow /
// dataGridBodyRowClass below). The header row's own background is the
// common `bg-muted/40` case; the stripped/no-header-background permutations
// are not separately mirrored here (a documented simplification, not a
// silent gap).
// `--z-sticky-header` (T2 fix round 2, not `--z-sticky-content`): the pinned
// HEADER cell must sit at the SAME step as the sticky `<thead>` it belongs
// to, one above pinned BODY cells - else at <=640px the pinned body column
// scrolls OVER the header instead of sliding under it.
// `bg-muted` NOT `bg-muted/40` (T2 fix round 3): the header row paints its
// OWN `bg-muted/40` tint underneath every `th` including this one, so a
// translucent pin only ever composed with its own row's colour in isolated
// testing - on a real horizontal scroll, the header text of every column
// scrolling UNDER the sticky cell shows straight through the 40% alpha. The
// pinned cell must be fully OPAQUE (solid `bg-muted`, matching the row's
// tint family without the alpha) so nothing beneath can bleed into it. Same
// simplification as the comment above - hardcodes the common case
// (`headerBackground: true`, `stripped: false`), which is every list in the
// app today.
const MOBILE_PIN_CLASS_HEAD =
  'max-sm:sticky! max-sm:start-0! max-sm:z-(--z-sticky-header)! max-sm:bg-muted! max-sm:data-pinned:static!';
// `group-hover:` here is already hover-capable-gated by Tailwind v4's OWN
// default `hover` variant (compiles to `&:hover { @media (hover: hover) }`)
// - no project override in `css/` and none needed, so no arbitrary
// `[@media(hover:hover)]:` wrapper (T2 fix round 2 animation-review nit).
// Eases with `transition-[background-color]` (T2 fix round 2) so the pinned
// cell's background follows its row's hover/select/stripe change instead of
// snapping.
// `bg-(--pinned-cell-hover)` / `bg-(--pinned-cell-selected)` NOT `bg-muted/40`
// / `bg-muted/50` (T2 fix round 3): the row itself is deliberately translucent
// (blends into whatever ancestor surface it's on), but the pinned cell has no
// ancestor at these screen pixels - the columns scrolling underneath are
// unrelated data, not a backdrop - so a live scroll showed a selected/hovered
// row's OWN date/status text bleeding straight through the pinned cell. The
// two tokens (`css/config.reui.css`) pre-mix the same alpha against
// `--background` into an opaque colour, keeping the relative visual weight
// (selected reads a touch stronger than hover) with nothing left to bleed.
const MOBILE_PIN_CLASS_BODY =
  'max-sm:sticky! max-sm:start-0! max-sm:z-(--z-sticky-content)! max-sm:bg-background! max-sm:data-pinned:static! ' +
  'transition-[background-color] duration-(--duration-fast) ease-(--ease-standard) ' +
  'group-hover:max-sm:bg-(--pinned-cell-hover)! group-data-[state=selected]:max-sm:bg-(--pinned-cell-selected)!';
// Striped legs (T2 fix round 2 finding 3): only apply when the row itself
// stripes (`tableLayout.stripped`) - unconditional before this, so a
// non-stripped list's pinned cell darkened on odd rows for no reason.
// `--pinned-cell-striped` (T2 fix round 3, same reasoning as above) replaces
// `bg-muted/90` - 90% alpha reads as opaque in isolation but still lets a
// sliver of scrolled-under content show at the cell's edges.
const MOBILE_PIN_CLASS_BODY_STRIPED =
  'group-odd:max-sm:bg-(--pinned-cell-striped)! group-hover:group-odd:max-sm:bg-muted!';
// T2 fix round 3: a `position: sticky` table cell does not reliably clip its
// own overflowing content via `overflow: hidden` (a real cross-browser
// rendering gap on sticky cells inside a table) - a cell's content is
// commonly a `flex flex-col` wrapper (title + subtitle) rather than a bare
// text node, and the inherited `nowrap` from the cell's own `truncate` class
// lets that flex box grow past the cell's box instead of wrapping, bleeding
// into the next (unrelated, now-scrolled-under) column's text. A plain,
// NON-sticky wrapper `div` around the cell's children establishes its own
// ordinary block-level clip that is not subject to the sticky-cell bug -
// applied ONLY on the mobile-pinned cell so every other cell's layout is
// untouched.
const MOBILE_PIN_CONTENT_CLASS_BODY = 'max-sm:overflow-hidden max-sm:truncate';

/**
 * Skeleton rows render ONLY while there is nothing worth showing yet
 * (AC-DLA-15) - a first load, or `loadingMode="skeleton"` with zero rows.
 * `isPlaceholderData` (kept rows, dimmed) is a SEPARATE state and must never
 * also draw skeletons on top of the rows it is holding.
 */
function shouldShowSkeletonRows<TData>(
  props: { loadingMode?: 'skeleton' | 'spinner'; isPlaceholderData?: boolean },
  isLoading: boolean,
  table: Table<TData>,
): boolean {
  return Boolean(
    props.loadingMode === 'skeleton' &&
      isLoading &&
      !props.isPlaceholderData &&
      table.getRowModel().rows.length === 0 &&
      table.getState().pagination?.pageSize,
  );
}

function DataGridTableBase({ children }: { children: ReactNode }) {
  const { props, table } = useDataGrid();
  const { ref: scrollerRef, isFading } = useHorizontalOverflow<HTMLDivElement>();

  // `getTotalSize()` is the sum of the visible leaf columns' widths - a
  // DEFINITE length the browser can resolve, unlike `min-w-max` on a
  // `table-layout: fixed` table (fixed layout ignores content by design, so
  // Chrome resolves `max-content` to its "infinite" sentinel and scales every
  // column up to fill it instead of the grid actually overflowing).
  const totalSize = table.getTotalSize();

  return (
    // `min-w-0`: `CardTable` (the usual ancestor) is `display: grid`, and a
    // grid/flex item defaults to `min-width: auto` - without this the item
    // refuses to shrink below the TABLE's full intrinsic width, so the
    // scroller never actually clips and the whole PAGE scrolls sideways
    // instead of just the grid (caught live on Users at 375, not by any
    // unit test - jsdom has no real layout to reproduce it).
    <div className="relative min-w-0">
      <div
        ref={scrollerRef}
        data-slot="data-grid-scroller"
        className={cn('overflow-x-auto overscroll-x-contain', props.tableClassNames?.scroller)}
      >
        <table
          data-slot="data-grid-table"
          style={totalSize > 0 ? { minWidth: `${totalSize}px` } : undefined}
          className={cn(
            'w-full tabular-nums align-middle caption-bottom text-left rtl:text-right text-foreground font-normal text-sm',
            !props.tableLayout?.columnsDraggable && 'border-separate border-spacing-0',
            props.tableLayout?.width === 'fixed' ? 'table-fixed' : 'table-auto',
            props.tableClassNames?.base,
          )}
        >
          {children}
        </table>
      </div>
      {/* Always mounted (AC-DLA-14 fix round 1) - no mount/unmount, no
          mask-image toggling. `data-fade` alone drives the opacity so a
          fast resize/reorder never races a conditional render. */}
      <div
        aria-hidden="true"
        data-slot="data-grid-fade"
        data-fade={isFading}
        className="pointer-events-none absolute inset-y-0 end-0 w-8 bg-gradient-to-l from-background to-transparent opacity-0 transition-opacity duration-(--duration-fast) ease-(--ease-standard) data-[fade=true]:opacity-100"
      />
    </div>
  );
}

function DataGridTableHead({ children }: { children: ReactNode }) {
  const { props } = useDataGrid();

  return (
    <thead
      className={cn(
        props.tableClassNames?.header,
        props.tableLayout?.headerSticky && props.tableClassNames?.headerSticky,
      )}
    >
      {children}
    </thead>
  );
}

function DataGridTableHeadRow<TData>({
  children,
  headerGroup,
}: {
  children: ReactNode;
  headerGroup: HeaderGroup<TData>;
}) {
  const { props } = useDataGrid();

  return (
    <tr
      key={headerGroup.id}
      // `group`: the mobile-pinned header cell (AC-DLA-13) matches this row's
      // own background rather than carrying a hardcoded one of its own.
      className={cn(
        'group bg-muted/40',
        props.tableLayout?.headerBorder && '[&>th]:border-b',
        props.tableLayout?.cellBorder && '[&_>:last-child]:border-e-0',
        props.tableLayout?.stripped && 'bg-transparent',
        props.tableLayout?.headerBackground === false && 'bg-transparent',
        props.tableClassNames?.headerRow,
      )}
    >
      {children}
    </tr>
  );
}

function DataGridTableHeadRowCell<TData>({
  children,
  header,
  dndRef,
  dndStyle,
}: {
  children: ReactNode;
  header: Header<TData, unknown>;
  dndRef?: React.Ref<HTMLTableCellElement>;
  dndStyle?: CSSProperties;
}) {
  const { props } = useDataGrid();

  const { column } = header;
  const isPinned = column.getIsPinned();
  const isLastLeftPinned = isPinned === 'left' && column.getIsLastColumn('left');
  const isFirstRightPinned = isPinned === 'right' && column.getIsFirstColumn('right');
  const headerCellSpacing = headerCellSpacingVariants({
    size: props.tableLayout?.dense ? 'dense' : 'default',
  });
  const isMobilePinned =
    !isPinned && column.getIndex() === firstDataColumnIndex(header.headerGroup.headers.map((h) => h.column));

  return (
    <th
      key={header.id}
      ref={dndRef}
      style={{
        ...(props.tableLayout?.width === 'fixed' && {
          width: `${header.getSize()}px`,
        }),
        ...(props.tableLayout?.columnsPinnable && column.getCanPin() && getPinningStyles(column)),
        ...(dndStyle ? dndStyle : null),
      }}
      data-pinned={isPinned || undefined}
      data-last-col={isLastLeftPinned ? 'left' : isFirstRightPinned ? 'right' : undefined}
      className={cn(
        'relative h-10 text-left rtl:text-right align-middle font-normal text-accent-foreground [&:has([role=checkbox])]:pe-0',
        headerCellSpacing,
        props.tableLayout?.cellBorder && 'border-e',
        props.tableLayout?.columnsResizable && column.getCanResize() && 'truncate',
        isMobilePinned && MOBILE_PIN_CLASS_HEAD,
        props.tableLayout?.columnsPinnable &&
          column.getCanPin() &&
          '[&:not([data-pinned]):has(+[data-pinned])_div.cursor-col-resize:last-child]:opacity-0 [&[data-last-col=left]_div.cursor-col-resize:last-child]:opacity-0 [&[data-pinned=left][data-last-col=left]]:border-e! [&[data-pinned=right]:last-child_div.cursor-col-resize:last-child]:opacity-0 [&[data-pinned=right][data-last-col=right]]:border-s! [&[data-pinned][data-last-col]]:border-border data-pinned:bg-muted/90 data-pinned:backdrop-blur-xs',
        header.column.columnDef.meta?.headerClassName,
        column.getIndex() === 0 || column.getIndex() === header.headerGroup.headers.length - 1
          ? props.tableClassNames?.edgeCell
          : '',
      )}
    >
      {children}
    </th>
  );
}

function DataGridTableHeadRowCellResize<TData>({ header }: { header: Header<TData, unknown> }) {
  const { column } = header;
  const resizeHandler = header.getResizeHandler();

  return (
    <div
      {...{
        onDoubleClick: () => column.resetSize(),
        // Pointer capture (AC-DLA-13): a fast drag that leaves the 16px handle
        // - or leaves the window - keeps resizing instead of silently
        // stopping.
        onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => {
          (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
        },
        onMouseDown: resizeHandler,
        onTouchStart: resizeHandler,
        className:
          'absolute top-0 h-full w-4 cursor-col-resize user-select-none touch-none -end-2 z-10 flex justify-center before:absolute before:w-px before:inset-y-0 before:bg-border before:-translate-x-px',
      }}
    />
  );
}

function DataGridTableRowSpacer() {
  return <tbody aria-hidden="true" className="h-2"></tbody>;
}

function DataGridTableBody({ children }: { children: ReactNode }) {
  const { props } = useDataGrid();

  return (
    <tbody
      className={cn(
        '[&_tr:last-child]:border-0',
        props.tableLayout?.rowRounded && '[&_td:first-child]:rounded-s-lg [&_td:last-child]:rounded-e-lg',
        // AC-DLA-15 fix round 1: the transition is UNCONDITIONAL so the
        // RESTORE (opacity-60 -> opacity-100, when isPlaceholderData flips
        // back off) eases too, not just the dim - a conditional transition
        // class would be absent the instant the condition clears, so the
        // restore would snap.
        'transition-opacity duration-(--duration-fast) ease-(--ease-standard)',
        // AC-DLA-15: the rows on screen are the PREVIOUS page's while the next
        // one loads - dimmed rather than replaced by a skeleton.
        props.isPlaceholderData && 'opacity-60',
        props.tableClassNames?.body,
      )}
    >
      {children}
    </tbody>
  );
}

function DataGridTableBodyRowSkeleton({ children }: { children: ReactNode }) {
  const { table, props } = useDataGrid();

  return (
    <tr className={dataGridBodyRowClass(props, table.options.enableRowSelection ?? false, false, true)}>
      {children}
    </tr>
  );
}

function DataGridTableBodyRowSkeletonCell<TData>({ children, column }: { children: ReactNode; column: Column<TData> }) {
  const { props, table } = useDataGrid();
  const bodyCellSpacing = bodyCellSpacingVariants({
    size: props.tableLayout?.dense ? 'dense' : 'default',
  });

  return (
    <td
      className={cn(
        'align-middle',
        bodyCellSpacing,
        props.tableLayout?.cellBorder && 'border-e',
        props.tableLayout?.columnsResizable && column.getCanResize() && 'truncate',
        column.columnDef.meta?.cellClassName,
        props.tableLayout?.columnsPinnable &&
          column.getCanPin() &&
          '[&[data-pinned=left][data-last-col=left]]:border-e! [&[data-pinned=right][data-last-col=right]]:border-s! [&[data-pinned][data-last-col]]:border-border data-pinned:bg-background/90 data-pinned:backdrop-blur-xs"',
        column.getIndex() === 0 || column.getIndex() === table.getVisibleFlatColumns().length - 1
          ? props.tableClassNames?.edgeCell
          : '',
      )}
    >
      {children}
    </td>
  );
}

/**
 * Anything inside a row that owns its own click - a checkbox, a menu trigger,
 * an inline action button. A row that opens a record must not also swallow
 * one of these, and the alternative is every one of them remembering
 * `stopPropagation` (AC-DLA-14).
 */
const ROW_INTERACTIVE_SELECTOR =
  'a,button,input,select,textarea,label,[role="checkbox"],[role="menuitem"],[role="combobox"]';

function fromOwnRowControl(target: EventTarget | null): boolean {
  return Boolean((target as Element | null)?.closest?.(ROW_INTERACTIVE_SELECTOR));
}

/**
 * `'#'`/`''` from a `rowHref` callback is AC-DLA-29's sentinel for "this
 * particular row has no detail page" (a list otherwise wired for navigation
 * can still have non-navigable rows) - the primitive itself must treat it as
 * an opt-out (no tabIndex, no push, no prefetch, no pointer cursor), not
 * leave it to every caller to remember (T2 fix round 2). A type guard, not a
 * plain boolean check, so the caller's `href` narrows to `string`.
 */
function hasRowHref(href: string | undefined): href is string {
  return Boolean(href) && href !== '#';
}

/**
 * The shared row classes for BOTH branches (`rowHref` and `onRowClick`), so
 * the skeleton row's cursor and the live row's cursor cannot drift apart.
 *
 * `unknownHref` (T2 fix round 2) is the skeleton placeholder's case ONLY: a
 * skeleton row has no `row.original` to resolve `rowHref` against yet, so it
 * keeps the old list-level "this list navigates" cursor heuristic
 * (`props.rowHref` configured at all). A REAL row instead passes the
 * per-row `isLinkRow` it actually resolved - so a `'#'`/`''` opt-out (AC-
 * DLA-29) correctly drops the cursor even though the list's `rowHref` prop
 * is otherwise set.
 */
function dataGridBodyRowClass<TData>(
  props: {
    rowHref?: (row: TData) => string;
    onRowClick?: (row: TData) => void;
    tableLayout?: { stripped?: boolean; rowBorder?: boolean; cellBorder?: boolean };
    tableClassNames?: { bodyRow?: string };
  },
  // TanStack's `enableRowSelection` table option is `boolean | ((row) =>
  // boolean)`; only truthiness matters here (a per-row select COLUMN exists
  // or it does not), never which row it is evaluated for.
  enableRowSelection: unknown,
  isLinkRow: boolean,
  unknownHref = false,
): string {
  return cn(
    // `group`: the mobile-pinned body cell (AC-DLA-13) matches this row's
    // own hover/selected/striped state rather than carrying a flat
    // background of its own.
    'group hover:bg-muted/40 data-[state=selected]:bg-muted/50',
    (isLinkRow || Boolean(props.onRowClick) || (unknownHref && Boolean(props.rowHref))) && 'cursor-pointer',
    isLinkRow &&
      // AC-DLA-14 fix round 1: `background-color` (the active/hover states)
      // AND `opacity` (T5's pending-row dim) both transition; no
      // `motion-reduce:transition-none` - the tokens already collapse to
      // ~0 under reduced motion (T1's preference block), so a second,
      // per-component override here was redundant.
      'active:bg-muted/60 transition-[background-color,opacity] duration-(--duration-fast) ease-(--ease-standard) ' +
        // Inset ring (fix round 1): the scroller clips an outer
        // focus-visible ring, so the row needs its own visible indicator.
        'focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
    !props.tableLayout?.stripped &&
      props.tableLayout?.rowBorder &&
      'border-b border-border [&:not(:last-child)>td]:border-b',
    props.tableLayout?.cellBorder && '[&_>:last-child]:border-e-0',
    props.tableLayout?.stripped && 'odd:bg-muted/90 hover:bg-transparent odd:hover:bg-muted',
    Boolean(enableRowSelection) && '[&_>:first-child]:relative',
    props.tableClassNames?.bodyRow,
  );
}

function DataGridTableBodyRow<TData>({
  children,
  row,
  dndRef,
  dndStyle,
}: {
  children: ReactNode;
  row: Row<TData>;
  dndRef?: React.Ref<HTMLTableRowElement>;
  dndStyle?: CSSProperties;
}) {
  const { props, table } = useDataGrid();
  const href = props.rowHref ? props.rowHref(row.original) : undefined;

  if (hasRowHref(href)) {
    return (
      <LinkableDataGridTableBodyRow href={href} dndRef={dndRef} dndStyle={dndStyle} row={row}>
        {children}
      </LinkableDataGridTableBodyRow>
    );
  }

  return (
    <tr
      ref={dndRef}
      style={{ ...(dndStyle ? dndStyle : null) }}
      data-state={table.options.enableRowSelection && row.getIsSelected() ? 'selected' : undefined}
      onClick={() => props.onRowClick && props.onRowClick(row.original)}
      className={dataGridBodyRowClass(props, table.options.enableRowSelection ?? false, false)}
    >
      {children}
    </tr>
  );
}

/**
 * The row when the list gave it a record to open (AC-DLA-14): keyboard-
 * reachable (`tabIndex=0`, click and Enter/Space push), middle-click opens a
 * new tab, hover prefetches once. NO `role="link"` (fix round 1) - it would
 * REPLACE the implicit `row` role for assistive tech, so a linkable row would
 * stop being a table row. The real, accessible `<a href>` lands in the
 * primary cell when T4 wires `rowHref` through `ResourceList` (AC-DLA-29).
 * Split out so `useRouter`/`usePrefetchOnce` are only called by a grid that
 * actually navigates.
 */
function LinkableDataGridTableBodyRow<TData>({
  href,
  row,
  dndRef,
  dndStyle,
  children,
}: {
  href: string;
  row: Row<TData>;
  dndRef?: React.Ref<HTMLTableRowElement>;
  dndStyle?: CSSProperties;
  children: ReactNode;
}) {
  const { props, table } = useDataGrid();
  const router = useRouter();
  const prefetchOnce = usePrefetchOnce();

  const open = useCallback(
    (newTab: boolean) => {
      if (newTab) {
        window.open(href, '_blank', 'noopener,noreferrer');
      } else {
        router.push(href);
      }
    },
    [href, router],
  );

  return (
    <tr
      ref={dndRef}
      style={{ ...(dndStyle ? dndStyle : null) }}
      tabIndex={0}
      data-state={table.options.enableRowSelection && row.getIsSelected() ? 'selected' : undefined}
      onClick={(event) => {
        // Primary button only - a synthetic dispatch or assistive tech can
        // deliver a `click` carrying button 1 (middle), and React's onClick
        // does not filter by button; auxclick owns the new tab.
        if (event.button !== 0) return;
        if (fromOwnRowControl(event.target)) return;
        open(event.metaKey || event.ctrlKey || event.shiftKey);
      }}
      onAuxClick={(event) => {
        if (event.button !== 1) return;
        if (fromOwnRowControl(event.target)) return;
        event.preventDefault();
        open(true);
      }}
      onKeyDown={(event) => {
        // Only the ROW's own keystrokes - Space in a cell's input types a
        // space, Space on the selection checkbox ticks the row.
        if (event.target !== event.currentTarget) return;
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        open(event.metaKey || event.ctrlKey || event.shiftKey);
      }}
      onPointerEnter={() => prefetchOnce(href)}
      className={dataGridBodyRowClass(props, table.options.enableRowSelection ?? false, true)}
    >
      {children}
    </tr>
  );
}

function DataGridTableBodyRowExpandded<TData>({ row }: { row: Row<TData> }) {
  const { props, table } = useDataGrid();

  return (
    <tr className={cn(props.tableLayout?.rowBorder && '[&:not(:last-child)>td]:border-b')}>
      <td colSpan={row.getVisibleCells().length}>
        {table
          .getAllColumns()
          .find((column) => column.columnDef.meta?.expandedContent)
          ?.columnDef.meta?.expandedContent?.(row.original)}
      </td>
    </tr>
  );
}

function DataGridTableBodyRowCell<TData>({
  children,
  cell,
  dndRef,
  dndStyle,
}: {
  children: ReactNode;
  cell: Cell<TData, unknown>;
  dndRef?: React.Ref<HTMLTableCellElement>;
  dndStyle?: CSSProperties;
}) {
  const { props } = useDataGrid();

  const { column, row } = cell;
  const isPinned = column.getIsPinned();
  const isLastLeftPinned = isPinned === 'left' && column.getIsLastColumn('left');
  const isFirstRightPinned = isPinned === 'right' && column.getIsFirstColumn('right');
  const bodyCellSpacing = bodyCellSpacingVariants({
    size: props.tableLayout?.dense ? 'dense' : 'default',
  });
  const isMobilePinned =
    !isPinned &&
    column.getIndex() === firstDataColumnIndex(row.getVisibleCells().map((c) => c.column));

  return (
    <td
      key={cell.id}
      ref={dndRef}
      {...(props.tableLayout?.columnsDraggable && !isPinned ? { cell } : {})}
      style={{
        ...(props.tableLayout?.columnsPinnable && column.getCanPin() && getPinningStyles(column)),
        ...(dndStyle ? dndStyle : null),
      }}
      data-pinned={isPinned || undefined}
      data-last-col={isLastLeftPinned ? 'left' : isFirstRightPinned ? 'right' : undefined}
      className={cn(
        'align-middle',
        bodyCellSpacing,
        props.tableLayout?.cellBorder && 'border-e',
        props.tableLayout?.columnsResizable && column.getCanResize() && 'truncate',
        cell.column.columnDef.meta?.cellClassName,
        isMobilePinned && MOBILE_PIN_CLASS_BODY,
        isMobilePinned && props.tableLayout?.stripped && MOBILE_PIN_CLASS_BODY_STRIPED,
        props.tableLayout?.columnsPinnable &&
          column.getCanPin() &&
          '[&[data-pinned=left][data-last-col=left]]:border-e! [&[data-pinned=right][data-last-col=right]]:border-s! [&[data-pinned][data-last-col]]:border-border data-pinned:bg-background/90 data-pinned:backdrop-blur-xs"',
        column.getIndex() === 0 || column.getIndex() === row.getVisibleCells().length - 1
          ? props.tableClassNames?.edgeCell
          : '',
      )}
    >
      {isMobilePinned ? <div className={MOBILE_PIN_CONTENT_CLASS_BODY}>{children}</div> : children}
    </td>
  );
}

function DataGridTableEmpty() {
  const { table, props } = useDataGrid();
  const totalColumns = table.getAllColumns().length;

  return (
    <tr>
      <td colSpan={totalColumns} className="text-center text-muted-foreground py-6">
        {props.emptyMessage || 'No data available'}
      </td>
    </tr>
  );
}

function DataGridTableLoader() {
  const { props } = useDataGrid();

  return (
    <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2">
      <div className="text-muted-foreground bg-card  flex items-center gap-2 px-4 py-2 font-medium leading-none text-sm border shadow-xs rounded-md">
        <svg
          className="animate-spin -ml-1 h-5 w-5 text-muted-foreground"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
        >
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3"></circle>
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          ></path>
        </svg>
        {props.loadingMessage || 'Loading...'}
      </div>
    </div>
  );
}

function DataGridTableRowSelect<TData>({ row, size }: { row: Row<TData>; size?: 'sm' | 'md' | 'lg' }) {
  return (
    <>
      <div
        className={cn('hidden absolute top-0 bottom-0 start-0 w-[2px] bg-primary', row.getIsSelected() && 'block')}
      ></div>
      <Checkbox
        checked={row.getIsSelected()}
        onCheckedChange={(value) => row.toggleSelected(!!value)}
        aria-label="Select row"
        size={size ?? 'sm'}
        className="align-[inherit]"
      />
    </>
  );
}

function DataGridTableRowSelectAll({ size }: { size?: 'sm' | 'md' | 'lg' }) {
  const { table, recordCount, isLoading } = useDataGrid();

  return (
    <Checkbox
      checked={table.getIsAllPageRowsSelected() || (table.getIsSomePageRowsSelected() && 'indeterminate')}
      disabled={isLoading || recordCount === 0}
      onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
      aria-label="Select all"
      size={size}
      className="align-[inherit]"
    />
  );
}

function DataGridTable<TData>() {
  const { table, isLoading, props } = useDataGrid();
  const pagination = table.getState().pagination;
  const showSkeleton = shouldShowSkeletonRows(props, isLoading, table);

  return (
    <DataGridTableBase>
      <DataGridTableHead>
        {table.getHeaderGroups().map((headerGroup: HeaderGroup<TData>, index) => {
          return (
            <DataGridTableHeadRow headerGroup={headerGroup} key={index}>
              {headerGroup.headers.map((header, index) => {
                const { column } = header;

                return (
                  <DataGridTableHeadRowCell header={header} key={index}>
                    {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                    {props.tableLayout?.columnsResizable && column.getCanResize() && (
                      <DataGridTableHeadRowCellResize header={header} />
                    )}
                  </DataGridTableHeadRowCell>
                );
              })}
            </DataGridTableHeadRow>
          );
        })}
      </DataGridTableHead>

      {(props.tableLayout?.stripped || !props.tableLayout?.rowBorder) && <DataGridTableRowSpacer />}

      <DataGridTableBody>
        {showSkeleton && pagination?.pageSize ? (
          Array.from({ length: pagination.pageSize }).map((_, rowIndex) => (
            <DataGridTableBodyRowSkeleton key={rowIndex}>
              {table.getVisibleFlatColumns().map((column, colIndex) => {
                return (
                  <DataGridTableBodyRowSkeletonCell column={column} key={colIndex}>
                    {column.columnDef.meta?.skeleton}
                  </DataGridTableBodyRowSkeletonCell>
                );
              })}
            </DataGridTableBodyRowSkeleton>
          ))
        ) : table.getRowModel().rows.length ? (
          table.getRowModel().rows.map((row: Row<TData>, index) => {
            return (
              <Fragment key={row.id}>
                <DataGridTableBodyRow row={row} key={index}>
                  {row.getVisibleCells().map((cell: Cell<TData, unknown>, colIndex) => {
                    return (
                      <DataGridTableBodyRowCell cell={cell} key={colIndex}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </DataGridTableBodyRowCell>
                    );
                  })}
                </DataGridTableBodyRow>
                {row.getIsExpanded() && <DataGridTableBodyRowExpandded row={row} />}
              </Fragment>
            );
          })
        ) : (
          <DataGridTableEmpty />
        )}
      </DataGridTableBody>
    </DataGridTableBase>
  );
}

export {
  DataGridTable,
  DataGridTableBase,
  DataGridTableBody,
  DataGridTableBodyRow,
  DataGridTableBodyRowCell,
  DataGridTableBodyRowExpandded,
  DataGridTableBodyRowSkeleton,
  DataGridTableBodyRowSkeletonCell,
  DataGridTableEmpty,
  DataGridTableHead,
  DataGridTableHeadRow,
  DataGridTableHeadRowCell,
  DataGridTableHeadRowCellResize,
  DataGridTableLoader,
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
  DataGridTableRowSpacer,
  firstDataColumnIndex,
  shouldShowSkeletonRows,
};
