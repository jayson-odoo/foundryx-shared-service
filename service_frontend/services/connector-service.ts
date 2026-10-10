import { apiFetch } from '@/lib/api-client';
import type {
  ConnectorActivity,
  ConnectorBulkRevokeResult,
  ConnectorGrant,
  ConnectorGrantListParams,
  ConnectorGrantPage,
  ConnectorProduct,
  ConnectorRevokeResult,
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
