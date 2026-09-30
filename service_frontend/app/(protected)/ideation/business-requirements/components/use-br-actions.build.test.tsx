import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import type { StatusGraph } from '@/types/status-engine';
import { brWithBuild, buildInfo } from './br-build-fixtures';
import { useBrActions } from './use-br-actions';

const statusGraph = vi.fn();
vi.mock('@/services/business-requirement-service', () => ({
  businessRequirementService: {
    statusGraph: () => statusGraph(),
    setStatus: vi.fn(),
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
    isArchived: false,
    isDefault: false,
    positionX: null,
    positionY: null,
    isSystem: true,
    recordCount: 0,
  };
}

const edge = (id: string, from: string, to: string, label: string, sortOrder: number) => ({
  id,
  entityType: 'ideation_business_requirement',
  fromStatusId: from,
  toStatusId: to,
  label,
  sortOrder,
  roles: [],
  notifications: [],
});

const GRAPH: StatusGraph = {
  entityType: 'ideation_business_requirement',
  source: 'platform',
  statuses: [
    node('s-ready', 'ready', 'Ready'),
    node('s-stb', 'sent_to_build', 'Sent to build'),
    node('s-draft', 'draft', 'Draft'),
  ],
  transitions: [
    edge('br-tr-send-to-build', 's-ready', 's-stb', 'Send to build', 1),
    edge('br-tr-send-to-build-2', 's-ready', 's-stb', 'Send to build', 2),
    edge('br-tr-ready-draft', 's-ready', 's-draft', 'Back to draft', 3),
    edge('br-tr-build-back', 's-stb', 's-ready', 'Back to ready', 1),
  ],
};

beforeEach(() => statusGraph.mockReset().mockResolvedValue(GRAPH));

describe('useBrActions send-to-build edges (AC-STB-07)', () => {
  it('AC-STB-07 filters out br-tr-send-to-build* edges (they belong to the button)', async () => {
    const { result } = renderHook(() =>
      useBrActions(brWithBuild(buildInfo(), { status: 'ready' }), {
        onChanged: vi.fn(),
        onFieldErrors: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.length).toBeGreaterThan(0));
    const ids = result.current.map((a) => a.id);
    expect(ids).toEqual(['transition-br-tr-ready-draft']);
    expect(ids.some((i) => i.includes('br-tr-send-to-build'))).toBe(false);
  });

  it('AC-STB-07 keeps "Back to ready" (br-tr-build-back) on a sent BR', async () => {
    const { result } = renderHook(() =>
      useBrActions(brWithBuild(buildInfo({ state: 'sent' }), { status: 'sent_to_build' }), {
        onChanged: vi.fn(),
        onFieldErrors: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.length).toBe(1));
    expect(result.current[0].id).toBe('transition-br-tr-build-back');
    expect(result.current[0].label).toBe('Ready');
  });
});
