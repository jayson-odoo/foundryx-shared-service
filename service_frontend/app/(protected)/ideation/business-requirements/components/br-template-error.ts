/**
 * Issue #90 W2 (AC-90-2xx): the `br_template_unavailable` 422 detail code the
 * backend raises from `BusinessRequirementService.create` when no active BR
 * template is configured. Shared by the create dialog (pre-empts it via
 * `useBrTemplateStatus`, but a race can still 422 on submit) and the
 * promote-to-BR flow (same create endpoint, no pre-check) so both surfaces
 * show the SAME sentence.
 */
import { ApiError } from '@/lib/api-client';

export const NO_TEMPLATE_MESSAGE =
  'Ask an administrator to restore the Business Requirement template.';

export function isBrTemplateUnavailable(e: unknown): boolean {
  return (
    e instanceof ApiError &&
    e.status === 422 &&
    typeof e.detail === 'object' &&
    e.detail !== null &&
    (e.detail as { code?: unknown }).code === 'br_template_unavailable'
  );
}
