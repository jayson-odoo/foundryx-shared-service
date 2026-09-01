'use client';

import { useEffect, useMemo, useState } from 'react';
import { integrationService } from '@/services/integration-service';
import type { SearchSelectOption } from '@/components/platform/search-select';
import type { FilterGroup } from '@/types/resource';

/** The provider a Sorento consumer (push target) connection registers as. */
export const SORENTO_PROVIDER = 'sorento';

const PROVIDER_FILTER: FilterGroup = {
  kind: 'group',
  combinator: 'and',
  rules: [
    { kind: 'condition', field: 'provider', operator: 'eq', value: SORENTO_PROVIDER },
  ],
};

export interface UseAutocountConsumerConnectionsResult {
  /** Sorento consumer connections - the valid `sinkConnectionId` picks. */
  options: SearchSelectOption[];
  isLoading: boolean;
  /**
   * Why there is nothing to pick, when there is nothing to pick. Foolproof-UI:
   * a missing prerequisite is stated, never a silent empty dropdown.
   */
  emptyReason: string | null;
}

/**
 * The push-target picker's options (plan 14 hop 2). A company delivering to
 * Sorento needs a `consumer`/`sorento` connection to name - offering `sorento`
 * with none configured would guarantee a validation failure, so the picker
 * states the prerequisite instead.
 */
export function useAutocountConsumerConnections(): UseAutocountConsumerConnectionsResult {
  const [options, setOptions] = useState<SearchSelectOption[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    integrationService
      .list({ page: 0, pageSize: 200, filter: PROVIDER_FILTER })
      .then((connections) => {
        if (cancelled) return;
        setOptions(connections.data.map((c) => ({ label: c.name, value: c.id })));
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

  const emptyReason = useMemo(() => {
    if (isLoading || options.length > 0) return null;
    return 'No Sorento consumer connection is connected yet.';
  }, [isLoading, options.length]);

  return { options, isLoading, emptyReason };
}
