import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { ApiError } from '@/lib/api-client';
import type { StatusGraph } from '@/types/status-engine';
import type { BusinessRequirementDetail } from '@/types/business-requirement';
import { useBrActions } from './use-br-actions';

const statusGraph = vi.fn();
const setStatus = vi.fn();
vi.mock('@/services/business-requirement-service', () => ({
  businessRequirementService: {
    statusGraph: () => statusGraph(),
    setStatus: (...a: unknown[]) => setStatus(...a),
  },
}));

function node(id: string, key: string, label: string) {
  return {
    id,
    entityType: 'ideation_business_requirement',
    key,
    label,
    color: 'gray',
    sortOrder: 1,
    isInitial: key === 'draft',
    isTerminal: false,
    isActive: true,
    blocksAccess: false,
    isArchived: key === 'archived',
    isDefault: false,
    positionX: null,
    positionY: null,
    isSystem: true,
    recordCount: 0,
  };
}

const GRAPH: StatusGraph = {
  entityType: 'ideation_business_requirement',
  source: 'platform',
  statuses: [node('br-status-draft', 'draft', 'Draft'), node('br-status-ready', 'ready', 'Ready')],
  transitions: [
    {
      id: 'br-tr-promote',
      entityType: 'ideation_business_requirement',
      fromStatusId: 'br-status-draft',
      toStatusId: 'br-status-ready',
      label: 'Promote to ready',
      sortOrder: 1,
      roles: [],
      notifications: [],
    },
  ],
};

const br = (over: Partial<BusinessRequirementDetail> = {}): BusinessRequirementDetail => ({
  id: 'br-1',
  productId: 'prod-1',
  productName: 'Sorento CRM',
  status: 'draft',
  statusLabel: 'Draft',
  statusColor: 'gray',
  templateKey: 'business_requirement',
  templateVersion: 1,
  title: 'Order export',
  ideaCount: 0,
  createdAt: '2026-07-20T10:00:00Z',
  updatedAt: '2026-07-20T10:00:00Z',
  answers: {},
  templateDoc: { schemaVersion: 1, pages: [] },
  ...over,
});

describe('useBrActions', () => {
  beforeEach(() => {
    statusGraph.mockReset().mockResolvedValue(GRAPH);
    setStatus.mockReset();
  });

  it('renders the promote edge with the bare target label + .promote permission', async () => {
    const { result } = renderHook(() =>
      useBrActions(br(), { onChanged: vi.fn(), onFieldErrors: vi.fn() }),
    );
    await waitFor(() => expect(result.current.length).toBe(1));
    const action = result.current[0];
    // Bare target status name — no "Move to" prefix (EMS mandate).
    expect(action.label).toBe('Ready');
    expect(action.permission).toBe('ideation.business_requirements.promote');
  });

  it('surfaces per-field errors + friendly message on a 422 promote refusal', async () => {
    const onFieldErrors = vi.fn();
    setStatus.mockRejectedValue(
      new ApiError('Unprocessable', 422, undefined, {
        fieldErrors: { success_metric: 'This field is required.' },
        message: 'Add the required fields before promoting: Success metric',
      }),
    );
    const { result } = renderHook(() =>
      useBrActions(br(), { onChanged: vi.fn(), onFieldErrors }),
    );
    await waitFor(() => expect(result.current.length).toBe(1));

    await result.current[0].run([br()], { reload: vi.fn(), ctx: undefined, index: undefined });
    expect(onFieldErrors).toHaveBeenCalledWith({ success_metric: 'This field is required.' });
  });
});
