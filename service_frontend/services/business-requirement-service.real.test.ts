import { beforeEach, describe, expect, it, vi } from 'vitest';

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));

vi.mock('@/lib/api-client', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api-client')>('@/lib/api-client');
  return { ...actual, apiFetch };
});

// Imported AFTER the mock is registered.
import { realBusinessRequirementService as svc } from './business-requirement-service.real';

beforeEach(() => apiFetch.mockReset());

/**
 * Issue #90 W2 (AC-90-2xx): the "New business requirement" dialog reads
 * whether a BR template is active BEFORE offering Create - a new
 * `templateStatus()` boundary method backed by
 * `GET /ideation/business-requirements/template-status`.
 */
describe('realBusinessRequirementService.templateStatus', () => {
  it('reads the template-status endpoint and returns {active}', async () => {
    apiFetch.mockResolvedValue({ active: true });
    const result = await svc.templateStatus();
    expect(apiFetch).toHaveBeenCalledWith('/ideation/business-requirements/template-status');
    expect(result).toEqual({ active: true });
  });

  it('surfaces an inactive template', async () => {
    apiFetch.mockResolvedValue({ active: false });
    const result = await svc.templateStatus();
    expect(result).toEqual({ active: false });
  });
});
