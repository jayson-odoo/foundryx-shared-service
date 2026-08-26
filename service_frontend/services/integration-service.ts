/**
 * Integration service (plan 09; Resource-shell contract since plan 06 D6) -
 * the boundary the /settings/integrations surfaces talk to. Phase A binds the
 * MOCK; Phase B swaps `integrationService` to the real api-client impl in ONE
 * line (bottom).
 *
 * The interface IS the backend contract: `/integrations/providers` +
 * `/integrations/connections[...]` (paginated list + `/at` + `/export`, like
 * every Resource entity), gated by `integrations.read/manage`. Credentials are
 * write-only - never echoed back by any call.
 */
import type {
  Connection,
  ConnectionInput,
  IntegrationProvider,
  TestConnectionResult,
} from '@/types/integration';
import type { ListQuery, ListResult } from '@/types/resource';
import { realIntegrationService } from './integration-service.real';

export interface IntegrationService {
  /** Available providers + their config schemas (GET /integrations/providers). */
  providers(): Promise<IntegrationProvider[]>;
  /** Paginated/filterable connections list (GET /integrations/connections). */
  list(query: ListQuery): Promise<ListResult<Connection>>;
  /** One connection (GET /integrations/connections/{id}). */
  get(id: string): Promise<Connection>;
  /** Record-nav: the connection at `index` under `query` (GET …/at). */
  getAt(
    query: ListQuery,
    index: number,
  ): Promise<{ connection: Connection | null; total: number }>;
  /** CSV export honoring the current query (GET …/export). */
  exportCsv(query: ListQuery, columns: string[], ids?: string[]): Promise<string>;
  /** Create - status starts UNVERIFIED until a test passes. ONE active
   *  connection per type per tenant (plan 06 D7) - a second storage
   *  connection 409s with "disconnect X first". */
  create(input: ConnectionInput): Promise<Connection>;
  /** Update - omitted credential keys mean "keep existing secret". */
  update(id: string, input: Partial<ConnectionInput>): Promise<Connection>;
  /** Remove the connection (falls back to the platform default, plan 09 §5). */
  remove(id: string): Promise<void>;
  /** Inline test - no `target` = the provider's standard check (SMTP:
   *  connect + authenticate; storage: HEAD bucket + probe round-trip, via the
   *  CDN URL when configured, plan 06 D3); with `target` = the provider's
   *  targeted test (SMTP: send a real email). Either way updates
   *  status/lastTestedAt. */
  test(id: string, target?: string): Promise<TestConnectionResult>;
  /** Make a STORAGE connection the tenant's active write-target
   *  (POST …/{id}/activate). Deactivates every other storage connection. */
  activate(id: string): Promise<Connection>;
}

// Phase B swap done - mock retained in integration-service.mock.ts for tests.
export const integrationService: IntegrationService = realIntegrationService;
