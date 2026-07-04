/**
 * Branding service (sprint-2/03) — the boundary the branding surfaces talk to
 * (via hooks). Phase A binds the mock; Phase B swaps `brandingService` to the
 * real api-client impl in ONE line (bottom of file). The interface IS the
 * backend contract (plan 03).
 *
 * Scope rule: every admin method takes an optional `tenantId` — omitted = the
 * caller's OWN tenant (`/branding`, gated branding.read/manage); present = the
 * operator console acting on another tenant (`/platform/tenants/{id}/branding`,
 * gated tenants.manage_branding).
 */
import type {
  BrandingAssetKind,
  PublicBranding,
  TenantBranding,
  UpdateBrandingInput,
} from '@/types/branding';
import { realBrandingService } from './branding-service.real';

export interface BrandingService {
  /** The tenant's branding record (empty defaults when none saved yet). */
  get(tenantId?: string): Promise<TenantBranding>;
  /** Save slogan + token overrides; bumps `version`. */
  update(
    input: UpdateBrandingInput,
    tenantId?: string,
  ): Promise<TenantBranding>;
  /** Upload one asset (multipart in Phase B). Applies immediately. */
  uploadAsset(
    kind: BrandingAssetKind,
    file: File,
    tenantId?: string,
  ): Promise<TenantBranding>;
  removeAsset(
    kind: BrandingAssetKind,
    tenantId?: string,
  ): Promise<TenantBranding>;
  /**
   * Public branding for a host slug — pre-auth (sign-in page, tab metadata,
   * app shell). Unknown slug = Dreamz defaults with `isBranded: false`.
   */
  publicBranding(slug: string): Promise<PublicBranding>;
}

// Phase B: real api-client. (Mock retained in branding-service.mock.ts.)
export const brandingService: BrandingService = realBrandingService;
