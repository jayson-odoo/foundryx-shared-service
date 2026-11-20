import { apiFetch } from '@/lib/api-client';
import type {
  ConnectorActivity,
  ConnectorBulkRevokeResult,
  ConnectorGrant,
  ConnectorGrantListParams,
  ConnectorGrantPage,
  ConnectorProduct,
  ConnectorProductCreateInput,
  ConnectorProductSettings,
  ConnectorProductSettingsInput,
  ConnectorRevokeResult,
  ConnectorSettingsAuditItem,
  ConnectorTenantSettings,
  ConnectorTenantSettingsInput,
} from '@/types/connector';

export function listGrants(params: ConnectorGrantListParams): Promise<ConnectorGrantPage> {
  const p = new URLSearchParams();
  if (params.status) p.set('status', params.status);
  if (params.product) p.set('product', params.product);
  if (params.search) p.set('search', params.search);
  if (params.page !== undefined) p.set('page', String(params.page));
  if (params.pageSize !== undefined) p.set('page_size', String(params.pageSize));
  const qs = p.toString();
  return apiFetch<ConnectorGrantPage>(`/connector/grants${qs ? `?${qs}` : ''}`);
}

export function getGrant(id: string): Promise<ConnectorGrant> {
  return apiFetch<ConnectorGrant>(`/connector/grants/${encodeURIComponent(id)}`);
}

export function getGrantActivity(id: string): Promise<ConnectorActivity> {
  return apiFetch<ConnectorActivity>(`/connector/grants/${encodeURIComponent(id)}/activity`);
}

export function revokeGrant(id: string): Promise<ConnectorRevokeResult> {
  return apiFetch<ConnectorRevokeResult>(`/connector/grants/${encodeURIComponent(id)}/revoke`, {
    method: 'POST',
  });
}

export function bulkRevokeGrants(ids: string[]): Promise<ConnectorBulkRevokeResult> {
  return apiFetch<ConnectorBulkRevokeResult>('/connector/grants/bulk-revoke', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  });
}

export async function listProducts(): Promise<ConnectorProduct[]> {
  const res = await apiFetch<{ data: ConnectorProduct[] }>('/connector/products');
  return res.data;
}

export function refreshManifest(key: string): Promise<ConnectorProduct> {
  return apiFetch<ConnectorProduct>(
    `/connector/products/${encodeURIComponent(key)}/refresh-manifest`,
    { method: 'POST' },
  );
}

// --- settings in the database (lane SETTINGS-IN-DB-SS) ---------------------------------

export function getTenantSettings(): Promise<ConnectorTenantSettings> {
  return apiFetch<ConnectorTenantSettings>('/connector/settings');
}

export function updateTenantSettings(
  input: ConnectorTenantSettingsInput,
): Promise<ConnectorTenantSettings> {
  return apiFetch<ConnectorTenantSettings>('/connector/settings', {
    method: 'PUT',
    body: JSON.stringify(input),
  });
}

export async function listSettingsAudit(): Promise<ConnectorSettingsAuditItem[]> {
  const res = await apiFetch<{ data: ConnectorSettingsAuditItem[] }>('/connector/settings/audit');
  return res.data;
}

export function getProductSettings(key: string): Promise<ConnectorProductSettings> {
  return apiFetch<ConnectorProductSettings>(
    `/connector/products/${encodeURIComponent(key)}/settings`,
  );
}

export function createProduct(input: ConnectorProductCreateInput): Promise<ConnectorProductSettings> {
  return apiFetch<ConnectorProductSettings>('/connector/products', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function updateProductSettings(
  key: string,
  input: ConnectorProductSettingsInput,
): Promise<ConnectorProductSettings> {
  return apiFetch<ConnectorProductSettings>(
    `/connector/products/${encodeURIComponent(key)}/settings`,
    { method: 'PUT', body: JSON.stringify(input) },
  );
}

export function deleteProduct(key: string, confirmKey: string): Promise<{ ok: true }> {
  return apiFetch<{ ok: true }>(`/connector/products/${encodeURIComponent(key)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmKey }),
  });
}
