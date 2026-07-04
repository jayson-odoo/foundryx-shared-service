import type { ColumnDef } from '@tanstack/react-table';
import type { ListQuery, ListResult } from '@/types/resource';
import type { ResourceAction } from './types';
import type { ResourceListConfig } from './types';

/**
 * Build a minimal ResourceListConfig for an embedded related-list inside a detail
 * tab (e.g. a client's Leads, a quotation's Revisions). Reuses the system list
 * shell (table + search + columns) so related lists look like every other list,
 * with no-op defaults for the toolbar bits a related list doesn't need (export,
 * filters, bulk actions, create). Caller supplies the columns + fetcher.
 */
export function embeddedListConfig<T extends object>(opts: {
  viewKey: string;
  columns: ColumnDef<T>[];
  fetcher: (query: ListQuery) => Promise<ListResult<T>>;
  getRowId: (row: T) => string;
  rowHref: (row: T) => string;
  searchPlaceholder?: string;
  defaultSort?: ResourceListConfig<T>['defaultSort'];
  createLabel?: string;
  onCreate?: () => void;
  createPermission?: string;
  actions?: ResourceAction<T>[];
}): ResourceListConfig<T> {
  return {
    viewKey: opts.viewKey,
    columns: opts.columns,
    getRowId: opts.getRowId,
    rowHref: opts.rowHref,
    fetcher: opts.fetcher,
    exporter: async () => '', // related lists don't export
    filterFields: [],
    exportColumns: [],
    actions: opts.actions ?? [],
    searchPlaceholder: opts.searchPlaceholder,
    defaultSort: opts.defaultSort,
    createLabel: opts.createLabel,
    onCreate: opts.onCreate,
    createPermission: opts.createPermission,
  };
}
