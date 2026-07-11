/**
 * Developer Logs / Integration Activity types (sprint-4/12) — the wire contract
 * the console list/detail speak. Source-tagged generic log across inbound API /
 * embed / outbound Meta / webhook legs (Slice 1 = inbound_api only).
 *
 * Wire = camelCase, Z-suffixed datetimes (backend `IntegrationActivityItem`,
 * `app/schemas/integration_activity.py`).
 */

/** Where the activity came from (Slice 1 writes `inbound_api`; others reserved). */
export type IntegrationLogSource =
  | 'inbound_api'
  | 'embed_session'
  | 'outbound_meta'
  | 'webhook_delivery';

/** Outcome of the interaction. */
export type IntegrationLogStatus = 'success' | 'error' | 'pending';

/** One console row (list projection). */
export interface IntegrationLogItem {
  id: string;
  tenantId: string;
  traceId: string | null;
  source: IntegrationLogSource;
  workspaceId: string | null;
  apiKeyId: string | null;
  operation: string;
  method: string | null;
  status: IntegrationLogStatus;
  statusCode: number | null;
  errorCode: string | null;
  latencyMs: number | null;
  externalRef: string | null;
  createdAt: string; // ISO Z
}

/** Detail row — adds the redacted request/response summaries + error message. */
export interface IntegrationLogDetail extends IntegrationLogItem {
  errorMessage: string | null;
  requestSummary: Record<string, unknown> | null;
  responseSummary: Record<string, unknown> | null;
}

/** `GET /integration-logs` response (matches backend `IntegrationActivityListResponse`). */
export interface IntegrationLogListResponse {
  data: IntegrationLogItem[];
  total: number;
  page: number;
}
