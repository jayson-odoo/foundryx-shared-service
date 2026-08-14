/**
 * Real branding service - talks to FastAPI via the shared api-client.
 * Wired in Phase B. Endpoints follow plan sprint-2/03.
 */
import type {
  BrandingAssetKind,
  PublicBranding,
  TenantBranding,
  UpdateBrandingInput,
} from '@/types/branding';
import { apiFetch } from '@/lib/api-client';
import type { BrandingService } from './branding-service';

/** Own-tenant vs operator-console route prefix (one service, two gates). */
const base = (tenantId?: string): string =>
  tenantId ? `/platform/tenants/${tenantId}/branding` : '/branding';

// Public endpoint base - mirrors api-client's BASE_URL resolution.
const PUBLIC_API =
  process.env.NEXT_PUBLIC_BACKEND_API_URL || 'http://localhost:8001';

export const realBrandingService: BrandingService = {
  get(tenantId) {
    return apiFetch<TenantBranding>(base(tenantId));
  },
  update(input: UpdateBrandingInput, tenantId) {
    return apiFetch<TenantBranding>(base(tenantId), {
      method: 'PUT',
      body: JSON.stringify(input),
    });
  },
  uploadAsset(kind: BrandingAssetKind, file: File, tenantId) {
    const form = new FormData();
    form.append('file', file);
    return apiFetch<TenantBranding>(`${base(tenantId)}/assets/${kind}`, {
      method: 'POST',
      body: form,
    });
  },
  removeAsset(kind: BrandingAssetKind, tenantId) {
    return apiFetch<TenantBranding>(`${base(tenantId)}/assets/${kind}`, {
      method: 'DELETE',
    });
  },
  async publicBranding(slug) {
    // Deliberately NOT apiFetch: the endpoint is public and apiFetch pays a
    // getSession() roundtrip per call - pure waste on the session-less
    // sign-in page (review finding).
    const res = await fetch(`${PUBLIC_API}/public/branding/${slug}`);
    if (!res.ok) throw new Error('Could not load branding.');
    return (await res.json()) as PublicBranding;
  },
};
