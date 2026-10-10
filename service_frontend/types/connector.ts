/** Claude connector wire types (plan sprint-4/19). Mirrors the backend camelCase wire. */

export type ConnectorGrantStatus = 'active' | 'revoked' | 'expired';

export interface ConnectorGrant {
  id: string;
  status: ConnectorGrantStatus;
  product: string;
  productName: string;
  productUserId: string;
  userName: string;
  userEmail?: string | null;
  clientName: string;
  grantedAt: string;
  consentedAt?: string | null;
  lastUsedAt: string | null;
  calls30d: number;
  revokedReason?: string | null;
}

export interface ConnectorCall {
  id: string;
  tool: string;
  statusCode: number | null;
  errorCode?: string | null;
  rows: number | null;
  chars: number | null;
  ms: number;
  truncated: boolean;
  args?: string | null;
  at: string;
}

/** One row of the merged Activity table: a tool call or a grant lifecycle event. */
export interface ConnectorActivityRow {
  id: string;
  kind: 'call' | 'event';
  at: string;
  event: string;
  tool: string | null;
  status: string | null;
  rows: number | null;
  chars: number | null;
  ms: number | null;
  args: string | null;
  truncated: boolean;
}

export interface ConnectorEvent {
  id: string;
  type: string;
  at: string;
  detail?: string | null;
}

export interface ConnectorActivity {
  calls: ConnectorCall[];
  events: ConnectorEvent[];
}

export interface ConnectorTool {
  name: string;
  method: string;
  path: string;
}

export type ConnectorSecretState = 'set' | 'missing';

export interface ConnectorProduct {
  key: string;
  displayName?: string;
  mcpUrl: string;
  consentUrl: string;
  apiBase: string;
  manifestVersion: string;
  toolCount: number;
  tools?: ConnectorTool[];
  fetchedAt: string | null;
  stale: boolean;
  lastError: string | null;
  secrets: { ssToProduct: ConnectorSecretState; productToSs: ConnectorSecretState };
  status?: 'ok' | 'misconfigured';
}

export interface ConnectorRevokeResult {
  ok: true;
}

export interface ConnectorBulkRevokeResult {
  revoked: number;
}

export interface ConnectorGrantListParams {
  status?: ConnectorGrantStatus;
  product?: string;
  search?: string;
  page?: number;
  pageSize?: number;
}

export interface ConnectorGrantPage {
  data: ConnectorGrant[];
  total: number;
  page: number;
}

// --- settings in the database (lane SETTINGS-IN-DB-SS) ---------------------------------

/** Where an effective value comes from: saved here, the server environment, or built in. */
export type ConnectorSettingSource = 'database' | 'environment' | 'default' | 'unset' | 'unreadable';

export interface ConnectorSettingValue {
  value: string | null;
  source: ConnectorSettingSource;
}

export interface ConnectorSecretValue {
  state: 'set' | 'missing' | 'unreadable';
  source: ConnectorSettingSource;
}

export type ConnectorProductField =
  | 'displayName'
  | 'connectionId'
  | 'consentUrl'
  | 'apiBaseUrl'
  | 'issuer'
  | 'consentAudience'
  | 'callAudience';

export type ConnectorSecretSlot = 'ssToProduct' | 'productToSs';

export interface ConnectorProductSettings {
  key: string;
  /** A database row exists (only then can it be deleted). */
  stored: boolean;
  status: 'ok' | 'misconfigured';
  fields: Record<ConnectorProductField, ConnectorSettingValue>;
  secrets: Record<ConnectorSecretSlot, ConnectorSecretValue>;
}

/** Omitted = unchanged; '' = clear (fall back); blank secret = keep. */
export type ConnectorProductSettingsInput = Partial<Record<ConnectorProductField, string>> & {
  ssToProductSecret?: string;
  productToSsSecret?: string;
  clearSecrets?: ConnectorSecretSlot[];
};

export interface ConnectorProductCreateInput extends ConnectorProductSettingsInput {
  key: string;
}

export type ConnectorTenantField =
  | 'publicBaseUrl'
  | 'allowedClientCidrs'
  | 'redirectAllowlist'
  | 'manifestTtlSeconds'
  | 'callTimeoutSeconds'
  | 'callLogRetentionDays';

export type ConnectorTenantSettings = Record<ConnectorTenantField, ConnectorSettingValue> & {
  /** Issue #118: the allow-list can be spoofed through X-Forwarded-For. */
  forwardedForWarning: boolean;
  /** Deployment limits a saved value must stay within (only those the server sets). */
  ceilings: Partial<Record<ConnectorTenantField, string>>;
};

/** Omitted = unchanged; null = clear (fall back to environment/default). */
export interface ConnectorTenantSettingsInput {
  publicBaseUrl?: string | null;
  allowedClientCidrs?: string | null;
  redirectAllowlist?: string | null;
  manifestTtlSeconds?: number | null;
  callTimeoutSeconds?: number | null;
  callLogRetentionDays?: number | null;
}

export interface ConnectorSettingsAuditItem {
  id: string;
  target: string;
  action: 'created' | 'updated' | 'deleted';
  fields: string[];
  actorUserId: string | null;
  actorName: string | null;
  at: string;
}
