/**
 * Mock public form service (plan sprint-3/02, Phase A) - drives the public fill
 * page with no backend so every state is tunable. Slug conventions:
 *   `closed-*` → closed state, `full-*` → full state, `missing-*` → 404 (null),
 *   anything else → an open 2-field demo form.
 * Submit: a non-empty honeypot 422s (bot), `429-*` slug → RateLimitError,
 * `bad@`/empty email → a field error, else success.
 */
import { RateLimitError } from '@/lib/service-errors';
import type { FormDocument, PublicFormView } from '@/types/forms';
import { FormSubmitError } from './form-service';
import type { PublicFormService, PublicSubmitPayload } from './public-form-service';

const LATENCY = 250;
const wait = <T,>(v: T): Promise<T> => new Promise((r) => setTimeout(() => r(v), LATENCY));

const DEMO_DOC: FormDocument = {
  schemaVersion: 1,
  pages: [
    {
      id: 'pg-1',
      title: 'Your details',
      sections: [
        {
          id: 'sec-1',
          title: undefined,
          fields: [
            { id: 'f-name', type: 'text', key: 'name', label: 'Full name', required: true },
            { id: 'f-email', type: 'email', key: 'email', label: 'Email', required: true },
          ],
        },
      ],
    },
  ],
};

function viewFor(state: PublicFormView['state'], formSlug: string): PublicFormView {
  return {
    state,
    formId: `mock-${formSlug}`,
    versionId: 'v1',
    name: 'Community Event Registration',
    description: state === 'open' ? 'Tell us who is coming.' : null,
    definition: state === 'open' ? DEMO_DOC : null,
    paged: false,
    honeypotField: '_hp_company',
    message:
      state === 'closed'
        ? 'This form is closed.'
        : state === 'full'
          ? 'This form has reached its submission limit.'
          : null,
  };
}

export const mockPublicFormService: PublicFormService = {
  async view(_tenantSlug, formSlug) {
    if (formSlug.startsWith('missing-')) return wait(null);
    if (formSlug.startsWith('closed-')) return wait(viewFor('closed', formSlug));
    if (formSlug.startsWith('full-')) return wait(viewFor('full', formSlug));
    return wait(viewFor('open', formSlug));
  },

  async submit(_tenantSlug, formSlug, payload: PublicSubmitPayload) {
    await wait(null);
    if (payload.honeypot) throw new FormSubmitError({});
    if (formSlug.startsWith('429-')) throw new RateLimitError('Too many submissions.', 120);
    const errors: Record<string, string> = {};
    const email = String(payload.answers.email ?? '');
    if (!email || !email.includes('@')) errors.email = 'A valid email is required.';
    if (Object.keys(errors).length) throw new FormSubmitError(errors);
  },
};
