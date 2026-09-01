/**
 * Public (pre-auth) form service boundary (plan sprint-3/02, slice 2). The
 * anonymous fill page consumes this - NO NextAuth session, NO Bearer (uses
 * `publicFetch`). Tenant is derived from the subdomain frontend-side and carried
 * in the path (the branding public-route precedent); the form is addressed by
 * its per-tenant slug. Unknown tenant / non-public / unpublished form = a
 * uniform 404 surfaced here as `null` (no enumeration). 422 carries the same
 * `{fieldErrors}` contract as the internal submit; 429 → `RateLimitError`.
 */
import { ApiError, publicFetch } from '@/lib/api-client';
import { RateLimitError } from '@/lib/service-errors';
import type { FormAnswers, PublicFormView } from '@/types/forms';
import { FormSubmitError } from './form-service';
import { realPublicFormService } from './public-form-service.real';

export interface PublicSubmitPayload {
  answers: FormAnswers;
  /** Bot-trap input value - must post back empty (D12). */
  honeypot: string;
}

export interface PublicFormService {
  /** Resolve the public fill view. `null` = uniform 404 (unknown/non-public/
   * unpublished). `state` distinguishes open vs closed/full for an EXISTING
   * public form. */
  view(tenantSlug: string, formSlug: string): Promise<PublicFormView | null>;
  /** Anonymous submit. Throws `FormSubmitError` (422), `RateLimitError` (429),
   * or `ApiError` (409 closed/full). */
  submit(tenantSlug: string, formSlug: string, payload: PublicSubmitPayload): Promise<void>;
}

/** Shared 422/429 mapping for both real + mock implementations. */
export function asSubmitError(error: unknown): Error {
  if (error instanceof ApiError) {
    if (error.status === 429) {
      return new RateLimitError(error.message, error.retryAfterSeconds ?? null);
    }
    if (error.status === 422 && error.detail && typeof error.detail === 'object') {
      const fieldErrors = (error.detail as { fieldErrors?: Record<string, string> }).fieldErrors;
      if (fieldErrors) return new FormSubmitError(fieldErrors);
    }
  }
  return error instanceof Error ? error : new Error('Submission failed.');
}

export { publicFetch };

// Phase B: swap to the real api-client implementation (one-line boundary).
export const publicFormService: PublicFormService = realPublicFormService;
