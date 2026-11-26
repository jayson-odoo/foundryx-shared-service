'use client';

import { useEffect, useState } from 'react';
import type { SearchSelectOption } from '@/components/platform/search-select';
import { autocountService } from '@/services/autocount-service';

export interface UseAutocountLineNotesConnectionsResult {
  /** The tenant's `sql_database` connections: the valid line notes database picks. */
  options: SearchSelectOption[];
  isLoading: boolean;
}

/** The "Line notes database" picker's options (plan 74): every `sql_database` connection of the tenant. */
export function useAutocountLineNotesConnections(): UseAutocountLineNotesConnectionsResult {
  const [options, setOptions] = useState<SearchSelectOption[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    autocountService
      .listSqlConnections()
      .then((rows) => {
        if (!cancelled) setOptions(rows.map((c) => ({ label: c.name, value: c.id })));
      })
      .catch(() => {
        if (!cancelled) setOptions([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { options, isLoading };
}
