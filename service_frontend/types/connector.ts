/** Claude connector wire types (plan sprint-4/19). Mirrors the backend camelCase wire. */

export type ConnectorGrantStatus = 'active' | 'revoked' | 'expired';

export interface ConnectorGrant {
  id: string;
  status: ConnectorGrantStatus;
  product: string;
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
  statusCode: number;
  rows: number;
  chars: number;
  ms: number;
  truncated: boolean;
  at: string;
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
