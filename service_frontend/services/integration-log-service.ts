/**
 * Integration-log service (sprint-4/12) - the boundary the Developers → Logs
 * console (list + detail) talks to via hooks. The interface IS the backend
 * contract (`app/api/v1/integration_logs.py`).
 *
 * Frontend-first: the UI iterated against `integration-log-service.mock`
 * (loading / error / empty / success states); the shipped boundary below is the
 * `.real` api-client impl - the mock→real swap is this one line.
 */
import type { ListQuery, ListResult } from '@/types/resource';
import type {
  IntegrationLogDetail,
  IntegrationLogItem,
  IntegrationLogSettings,
  IntegrationLogTrace,
} from '@/types/integration-logs';
import { realIntegrationLogService } from './integration-log-service.real';

export interface IntegrationLogService {
  /** Paginated, tenant-scoped log list (`GET /integration-logs`). */
  list(query: ListQuery): Promise<ListResult<IntegrationLogItem>>;
  /** One log row incl. redacted request/response (`GET /integration-logs/{id}`). */
  get(id: string): Promise<IntegrationLogDetail | null>;
  /** Ordered legs of one consumption (`GET /integration-logs/trace/{traceId}`). */
  getTrace(traceId: string): Promise<IntegrationLogTrace | null>;
  /** CSV export of the current query (shell export button). */
  export(query: ListQuery, columns: string[]): Promise<string>;
  /** Tenant retention settings (`GET /integration-logs/settings`). */
  getSettings(): Promise<IntegrationLogSettings>;
  /** Update the tenant retention window (`PUT /integration-logs/settings`). */
  updateSettings(retentionDays: number): Promise<IntegrationLogSettings>;
}

// Phase B: real api-client implementation is the shipped boundary.
export const integrationLogService: IntegrationLogService = realIntegrationLogService;
