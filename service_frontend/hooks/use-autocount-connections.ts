'use client';

import { useEffect, useMemo, useState } from 'react';
import { autocountService } from '@/services/autocount-service';
import { integrationService } from '@/services/integration-service';
import type { SearchSelectOption } from '@/components/platform/search-select';
import type { AutocountSourceKind } from '@/types/autocount';
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

/** One source's picker state - the SAME shape for both kinds so the form has one code path. */
export interface SourceConnectionsState {
  /** Connections of this provider not yet registered as a company - the ONLY valid picks. */
  options: SearchSelectOption[];
  /** The tenant holds at least one connection of this provider (bound or not). */
  hasAny: boolean;
  /** Every connection of this provider is already a company (nothing left to pick). */
  allBound: boolean;
  isLoading: boolean;
}

export interface UseAutocountSourceConnectionsResult {
  api: SourceConnectionsState;
  db: SourceConnectionsState;
  isLoading: boolean;
  /**
   * The Source toggle's default (AC-01-12): the first kind with an unbound
   * connection - API first when both have one, `db` when only it does, `api`
   * when neither does (its banner then explains why nothing is pickable).
   */
  defaultKind: AutocountSourceKind;
}

const EMPTY: SourceConnectionsState = {
  options: [],
  hasAny: false,
  allBound: false,
  isLoading: true,
};

/**
 * The connection picker's options for registering a company, per source
 * (plan sprint-5/01 §2.6).
 *
 * One connection maps to exactly one company - the vendor API resolves the
 * company from the AppId header, and a `sql_database` connection IS the
 * company's identity - so a connection that already has a company is excluded
 * from BOTH lists: offering it would guarantee a 409 (foolproof-UI). Both
 * kinds load together because the toggle's default depends on both.
 */
export function useAutocountSourceConnections(): UseAutocountSourceConnectionsResult {
  const [api, setApi] = useState<SourceConnectionsState>(EMPTY);
  const [db, setDb] = useState<SourceConnectionsState>(EMPTY);

  useEffect(() => {
    let cancelled = false;
    setApi(EMPTY);
    setDb(EMPTY);
    Promise.all([
      integrationService
        .list({ page: 0, pageSize: 200, filter: PROVIDER_FILTER })
        .then((r) => r.data)
        .catch(() => []),
      autocountService.listSqlConnections().catch(() => []),
      autocountService
        .listCompanies({ page: 0, pageSize: 200 })
        .then((r) => r.data)
        .catch(() => []),
    ]).then(([apiConnections, sqlConnections, companies]) => {
      if (cancelled) return;
      const taken = new Set(companies.map((c) => c.connectionId));
      const apiOptions = apiConnections
        .filter((c) => !taken.has(c.id))
        .map((c) => ({ label: c.name, value: c.id }));
      // The database IS the company's identity, so the label carries it.
      const dbOptions = sqlConnections
        .filter((c) => !taken.has(c.id))
        .map((c) => ({ label: `${c.name} · ${c.database}`, value: c.id }));
      setApi({
        options: apiOptions,
        hasAny: apiConnections.length > 0,
        allBound: apiConnections.length > 0 && apiOptions.length === 0,
        isLoading: false,
      });
      setDb({
        options: dbOptions,
        hasAny: sqlConnections.length > 0,
        allBound: sqlConnections.length > 0 && dbOptions.length === 0,
        isLoading: false,
      });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const isLoading = api.isLoading || db.isLoading;

  const defaultKind = useMemo<AutocountSourceKind>(() => {
    if (api.options.length > 0) return 'api';
    if (db.options.length > 0) return 'db';
    return 'api';
  }, [api.options.length, db.options.length]);

  return { api, db, isLoading, defaultKind };
}
