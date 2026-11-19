'use client';

/**
 * What a Foundryx UIUX list tells its column headers (search, filter and
 * sort from a header). Only `FxResourceList` provides it, so a header outside
 * one (any other DataGrid) keeps its legacy look even with the switch on.
 */
import { createContext, useContext } from 'react';
import type { SortState } from '@/types/resource';
import type { FxHeaderValue } from './list-logic';

export type FxHeaderKind = 'text' | 'date' | 'status';

export interface FxListHeaderContextValue {
  /** The header search or filter a column gets, or null for none. */
  kindOf: (columnId: string) => FxHeaderKind | null;
  /** Status ticks: the column's choices. */
  optionsOf: (columnId: string) => { label: string; value: string }[];
  valueOf: (columnId: string) => FxHeaderValue | undefined;
  setValue: (columnId: string, value: FxHeaderValue | undefined) => void;
  /** The list's own sort (not the table's). */
  sort: SortState | null;
  /** Up, then down, then back to the list's own order. */
  cycleSort: (columnId: string) => void;
  /** Settings "Search and filter from a header" / "Sort from a header". */
  searchOn: boolean;
  sortOn: boolean;
  timeZone: string;
}

export const FxListHeaderContext = createContext<FxListHeaderContextValue | null>(null);

export function useFxListHeader(): FxListHeaderContextValue | null {
  return useContext(FxListHeaderContext);
}
