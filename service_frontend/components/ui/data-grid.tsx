'use client';

import { createContext, ReactNode, useContext } from 'react';
import { cn } from '@/lib/utils';
import { ColumnFiltersState, RowData, SortingState, Table } from '@tanstack/react-table';

declare module '@tanstack/react-table' {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData extends RowData, TValue> {
    headerTitle?: string;
    headerClassName?: string;
    cellClassName?: string;
    skeleton?: ReactNode;
    expandedContent?: (row: TData) => ReactNode;
    /**
     * A structural column that never carries record data - a drag handle, an
     * icon-only affordance column, etc. Excluded from the mobile first-data-
     * column pin (AC-DLA-13) the same way `reorderable: false` columns are;
     * kept as its own flag because "not reorderable" and "not real data" are
     * different reasons a column can be structural (a fixed but genuinely
     * pinnable data column, e.g. an id column, sets `reorderable: false`
     * without being a utility column).
     */
    utility?: boolean;
  }
}

export type DataGridApiFetchParams = {
  pageIndex: number;
  pageSize: number;
  sorting?: SortingState;
  filters?: ColumnFiltersState;
  searchQuery?: string;
};

export type DataGridApiResponse<T> = {
  data: T[];
  empty: boolean;
  pagination: {
    total: number;
    page: number;
  };
};

export interface DataGridContextProps<TData extends object> {
  props: DataGridProps<TData>;
  table: Table<TData>;
  recordCount: number;
  isLoading: boolean;
}

export type DataGridRequestParams = {
  pageIndex: number;
  pageSize: number;
  sorting?: SortingState;
  columnFilters?: ColumnFiltersState;
};

export interface DataGridProps<TData extends object> {
  className?: string;
  table?: Table<TData>;
  recordCount: number;
  children?: ReactNode;
  onRowClick?: (row: TData) => void;
  /**
   * Each body row becomes a real link target to this href (AC-DLA-14): click,
   * Enter/Space and middle-click all open it, hover prefetches it once. Stays
   * undefined for lightbox-edited lists, which keep `onRowClick`. Neither prop
   * set = no pointer cursor, no row-level interaction.
   */
  rowHref?: (row: TData) => string;
  /**
   * True while the CURRENT rows are stale (a new page/sort/filter/search is
   * resolving) but kept on screen rather than replaced by a skeleton
   * (AC-DLA-15). Dims the body; the pagination strip stays mounted and
   * interactive throughout.
   */
  isPlaceholderData?: boolean;
  isLoading?: boolean;
  loadingMode?: 'skeleton' | 'spinner';
  loadingMessage?: ReactNode | string;
  emptyMessage?: ReactNode | string;
  tableLayout?: {
    dense?: boolean;
    cellBorder?: boolean;
    rowBorder?: boolean;
    rowRounded?: boolean;
    stripped?: boolean;
    headerBackground?: boolean;
    headerBorder?: boolean;
    headerSticky?: boolean;
    width?: 'auto' | 'fixed';
    columnsVisibility?: boolean;
    columnsResizable?: boolean;
    columnsPinnable?: boolean;
    columnsMovable?: boolean;
    columnsDraggable?: boolean;
    rowsDraggable?: boolean;
  };
  tableClassNames?: {
    base?: string;
    header?: string;
    headerRow?: string;
    headerSticky?: string;
    body?: string;
    bodyRow?: string;
    footer?: string;
    edgeCell?: string;
    /**
     * The ONE element that scrolls both axes (AC-DLA-13): bounded vertically
     * by `max-h-(--grid-max-h)` so `headerSticky` has something to stick
     * inside, and horizontally by `overflow-x-auto`. Override per list (a
     * tall embedded grid inside a tab/dialog needs its own bound instead of
     * the shell-relative default).
     */
    scroller?: string;
  };
}

const DataGridContext = createContext<
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  DataGridContextProps<any> | undefined
>(undefined);

function useDataGrid() {
  const context = useContext(DataGridContext);
  if (!context) {
    throw new Error('useDataGrid must be used within a DataGridProvider');
  }
  return context;
}

function DataGridProvider<TData extends object>({
  children,
  table,
  ...props
}: DataGridProps<TData> & { table: Table<TData> }) {
  return (
    <DataGridContext.Provider
      value={{
        props,
        table,
        recordCount: props.recordCount,
        isLoading: props.isLoading || false,
      }}
    >
      {children}
    </DataGridContext.Provider>
  );
}

function DataGrid<TData extends object>({ children, table, ...props }: DataGridProps<TData>) {
  const defaultProps: Partial<DataGridProps<TData>> = {
    loadingMode: 'skeleton',
    tableLayout: {
      dense: false,
      cellBorder: false,
      rowBorder: true,
      rowRounded: false,
      stripped: false,
      // AC-DLA-13: sticky by default - the grid brings its own bounded
      // scroller (DataGridTableBase), so a sticky header has something to
      // stick against. Per-list overridable (`--grid-max-h` is the bound).
      headerSticky: true,
      headerBackground: true,
      headerBorder: true,
      width: 'fixed',
      columnsVisibility: false,
      columnsResizable: true,
      columnsPinnable: false,
      columnsMovable: true,
      columnsDraggable: false,
      rowsDraggable: false,
    },
    tableClassNames: {
      base: '',
      header: '',
      headerRow: '',
      headerSticky: 'sticky top-0 z-(--z-sticky-content) bg-background',
      body: '',
      bodyRow: '',
      footer: '',
      edgeCell: '',
      // Bounded on the SAME element that scrolls sideways (AC-DLA-13 fix
      // round 1) - a separate horizontal-only scroller with an outer
      // vertical bound never actually lets the sticky header stick, since
      // `position: sticky`'s containing block is whichever ancestor
      // actually scrolls.
      scroller: 'max-h-(--grid-max-h) overflow-y-auto',
    },
  };

  const mergedProps: DataGridProps<TData> = {
    ...defaultProps,
    ...props,
    tableLayout: {
      ...defaultProps.tableLayout,
      ...(props.tableLayout || {}),
    },
    tableClassNames: {
      ...defaultProps.tableClassNames,
      ...(props.tableClassNames || {}),
    },
  };

  // Ensure table is provided
  if (!table) {
    throw new Error('DataGrid requires a "table" prop');
  }

  return (
    <DataGridProvider table={table} {...mergedProps}>
      {children}
    </DataGridProvider>
  );
}

function DataGridContainer({
  children,
  className,
  border = true,
}: {
  children: ReactNode;
  className?: string;
  border?: boolean;
}) {
  return (
    <div data-slot="data-grid" className={cn('grid w-full', border && 'border border-border rounded-lg', className)}>
      {children}
    </div>
  );
}

export { useDataGrid, DataGridProvider, DataGrid, DataGridContainer };
