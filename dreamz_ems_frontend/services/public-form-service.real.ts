/**
 * Real (api-client-backed) public form service (plan sprint-3/02). Calls the
 * unauthenticated `/public/forms/...` routes via `publicFetch`. A 404 on `view`
 * means unknown/non-public/unpublished → `null` (uniform, no enumeration).
 */
import { ApiError, publicFetch } from '@/lib/api-client';
import { buildSubmitBody } from '@/lib/form-submit-body';
import type { PublicFormView } from '@/types/forms';
import { asSubmitError, type PublicFormService } from './public-form-service';

function path(tenantSlug: string, formSlug: string): string {
  return `/public/forms/${encodeURIComponent(tenantSlug)}/${encodeURIComponent(formSlug)}`;
}

export const realPublicFormService: PublicFormService = {
  async view(tenantSlug, formSlug) {
    try {
      return await publicFetch<PublicFormView>(path(tenantSlug, formSlug));
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  },

  async submit(tenantSlug, formSlug, payload) {
    try {
      // Multipart when file fields carry staged uploads; JSON otherwise (D12).
      const { body } = buildSubmitBody(payload.answers, payload.honeypot);
      await publicFetch<void>(`${path(tenantSlug, formSlug)}/submissions`, {
        method: 'POST',
        body,
      });
    } catch (error) {
      throw asSubmitError(error);
    }
  },
};
