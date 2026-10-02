'use client';

import { useEffect, useMemo, useState } from 'react';
import { autocountService } from '@/services/autocount-service';
import type { SearchSelectOption } from '@/components/platform/search-select';
import type { AutocountApiConnection, AutocountConnectionAuth } from '@/types/autocount';

/** The core integrations provider key the `autocount` module registers as. */
export const AUTOCOUNT_PROVIDER = 'autocount';

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
   * The Source toggle's default: the first kind with an unbound connection -
   * `api` first when both have one, `db` when only it does, `api` when
   * neither does (its banner then explains why nothing is pickable).
   */
  defaultKind: 'api' | 'db';
  /**
   * Every unbound `autocount` connection, by id (sprint-5/08, AC-08-09) -
   * lets the connect form reveal the reference-prefix field for a No-auth
   * pick and derive its default text (from the connection's own `name`,
   * never the badged option label) without a second fetch.
   */
  apiConnectionsById: Record<string, AutocountApiConnection>;
}

const EMPTY: SourceConnectionsState = {
  options: [],
  hasAny: false,
  allBound: false,
  isLoading: true,
};

function authBadge(auth: AutocountConnectionAuth): string {
  return auth === 'none' ? 'No auth' : 'Basic auth';
}

/**
 * The connection picker's options for registering a company, per source
 * (plan sprint-5/01 §2.6; sprint-5/08 D1 - the `autocount` list now badges
 * each option by auth so a No-auth pick can be told apart from a Basic-auth
 * one before the operator ever submits).
 *
 * One connection maps to exactly one company - the vendor API resolves the
 * company from the AppId header (Basic auth) or the base URL alone (No
 * auth), and a `sql_database` connection IS the company's identity - so a
 * connection that already has a company is excluded from BOTH lists:
 * offering it would guarantee a 409 (foolproof-UI). Both kinds load together
 * because the toggle's default depends on both. The `api` list is sourced
 * from `autocountService.listApiConnections()` (AC-08-15) - the SAME
 * endpoint the task Source tab badges its connection picker from, so there
 * is one place that knows an `autocount` connection's auth, not two.
 */
export function useAutocountSourceConnections(): UseAutocountSourceConnectionsResult {
  const [api, setApi] = useState<SourceConnectionsState>(EMPTY);
  const [db, setDb] = useState<SourceConnectionsState>(EMPTY);
  const [apiConnectionsById, setApiConnectionsById] = useState<
    Record<string, AutocountApiConnection>
  >({});

  useEffect(() => {
    let cancelled = false;
    setApi(EMPTY);
    setDb(EMPTY);
    Promise.all([
      autocountService.listApiConnections().catch(() => [] as AutocountApiConnection[]),
      autocountService.listSqlConnections().catch(() => []),
      autocountService
        .listCompanies({ page: 0, pageSize: 200 })
        .then((r) => r.data)
        .catch(() => []),
    ]).then(([apiConnections, sqlConnections, companies]) => {
      if (cancelled) return;
      const taken = new Set(companies.map((c) => c.connectionId));
      const unboundApi = apiConnections.filter((c) => !taken.has(c.id));
      const apiOptions = unboundApi.map((c) => ({
        label: `${c.name} (${authBadge(c.auth)})`,
        value: c.id,
      }));
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
      setApiConnectionsById(Object.fromEntries(unboundApi.map((c) => [c.id, c])));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const isLoading = api.isLoading || db.isLoading;

  const defaultKind = useMemo<'api' | 'db'>(() => {
    if (api.options.length > 0) return 'api';
    if (db.options.length > 0) return 'db';
    return 'api';
  }, [api.options.length, db.options.length]);

  return { api, db, isLoading, defaultKind, apiConnectionsById };
}
