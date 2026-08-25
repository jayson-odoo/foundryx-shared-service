/**
 * Developer Logs / Integration Activity types (sprint-4/12) - the wire contract
 * the console list/detail speak. Source-tagged generic log across inbound API /
 * embed / outbound Meta / webhook legs (Slice 1 = inbound_api only).
 *
 * Wire = camelCase, Z-suffixed datetimes (backend `IntegrationActivityItem`,
 * `app/schemas/integration_activity.py`).
 */

/**
 * Where the activity came from (Slice 1 writes `inbound_api`; others reserved).
 * MIRRORS the backend's closed `ACTIVITY_SOURCES` tuple
 * (`app/models/integration_activity.py`) - add a value to BOTH or the console
 * type-mismatches the wire.
 */
export type IntegrationLogSource =
  | 'inbound_api'
  | 'embed_session'
  | 'outbound_meta'
  | 'webhook_delivery'
  | 'autocount';

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

/** Detail row - adds the redacted request/response summaries + error message. */
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

/**
 * `GET /integration-logs/trace/{traceId}` - the ordered legs (oldest→newest) of
 * ONE consumption: inbound API → outbound Meta → webhook delivery (sprint-4/12
 * Slice 2, AC-DLC-17). Matches backend `IntegrationActivityTraceResponse`.
 */
export interface IntegrationLogTrace {
  traceId: string;
  legs: IntegrationLogItem[];
}

/**
 * `GET/PUT /integration-logs/settings` - per-tenant retention window (sprint-4/12
 * Slice 3, AC-DLC-21). `isDefault` = using the deployment default (no override).
 * Matches backend `IntegrationLogSettingsOut`.
 */
export interface IntegrationLogSettings {
  retentionDays: number;
  isDefault: boolean;
}
