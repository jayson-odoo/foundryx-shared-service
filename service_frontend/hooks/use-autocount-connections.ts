'use client';

import { useEffect, useMemo, useState } from 'react';
import { autocountService } from '@/services/autocount-service';
import { integrationService } from '@/services/integration-service';
import type { SearchSelectOption } from '@/components/platform/search-select';
import type { FilterGroup } from '@/types/resource';

/** The core integrations provider key the `autocount` module registers as. */
export const AUTOCOUNT_PROVIDER = 'autocount';

const PROVIDER_FILTER: FilterGroup = {
  kind: 'group',
  combinator: 'and',
  rules: [
    { kind: 'condition', field: 'provider', operator: 'eq', value: AUTOCOUNT_PROVIDER },
  ],
};

export interface UseAutocountConnectionsResult {
  /** AutoCount connections not yet registered as a company - the ONLY valid picks. */
  options: SearchSelectOption[];
  isLoading: boolean;
  /**
   * Why there is nothing to pick, when there is nothing to pick. Foolproof-UI:
   * a missing prerequisite is stated, never left as a silent empty dropdown.
   */
  emptyReason: string | null;
}

/**
 * The connection picker's options for registering a company.
 *
 * One connection maps to exactly one company (the vendor API resolves the
 * company from the AppId header), so a connection that already has a company is
 * excluded - offering it would guarantee a 409.
 */
export function useAutocountConnections(): UseAutocountConnectionsResult {
  const [options, setOptions] = useState<SearchSelectOption[]>([]);
  const [totalConnections, setTotalConnections] = useState(0);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    Promise.all([
      integrationService.list({ page: 0, pageSize: 200, filter: PROVIDER_FILTER }),
      autocountService.listCompanies({ page: 0, pageSize: 200 }),
    ])
      .then(([connections, companies]) => {
        if (cancelled) return;
        const taken = new Set(companies.data.map((c) => c.connectionId));
        setTotalConnections(connections.data.length);
        setOptions(
          connections.data
            .filter((c) => !taken.has(c.id))
            .map((c) => ({ label: c.name, value: c.id })),
        );
      })
      .catch(() => {
        if (cancelled) return;
        setTotalConnections(0);
        setOptions([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const emptyReason = useMemo(() => {
    if (isLoading || options.length > 0) return null;
    if (totalConnections === 0) {
      return 'No AutoCount integration is connected yet.';
    }
    return 'Every AutoCount connection is already registered as a company.';
  }, [isLoading, options.length, totalConnections]);

  return { options, isLoading, emptyReason };
}
