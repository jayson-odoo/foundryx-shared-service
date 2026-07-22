import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const svc = {
  getPrerequisite: vi.fn(),
  listSkillOptions: vi.fn(),
};
vi.mock('@/services/ai-service', () => ({
  get aiService() {
    return svc;
  },
}));

import { useAiPrerequisite } from './use-ai-prerequisite';

beforeEach(() => {
  vi.clearAllMocks();
  svc.getPrerequisite.mockResolvedValue({
    hasConnection: true,
    connections: [
      { id: 'c1', name: 'Gemini key', provider: 'gemini', status: 'ACTIVE', isPlatform: false },
    ],
  });
  svc.listSkillOptions.mockResolvedValue([{ id: 's1', name: 'Grill me' }]);
});

describe('useAiPrerequisite (AC-BI-11)', () => {
  it('reports a configured workspace and its option sources', async () => {
    const { result } = renderHook(() => useAiPrerequisite());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.hasConnection).toBe(true);
    expect(result.current.connections).toHaveLength(1);
    expect(result.current.skills).toHaveLength(1);
  });

  it('flags a workspace with no LLM connection so the UI can warn up front', async () => {
    svc.getPrerequisite.mockResolvedValue({ hasConnection: false, connections: [] });
    const { result } = renderHook(() => useAiPrerequisite());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.hasConnection).toBe(false);
    expect(result.current.connections).toEqual([]);
  });

  it('degrades to "not configured" rather than throwing when the probe fails', async () => {
    svc.getPrerequisite.mockRejectedValue(new Error('boom'));
    svc.listSkillOptions.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useAiPrerequisite());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.hasConnection).toBe(false);
    expect(result.current.skills).toEqual([]);
  });

  it('surfaces the platform fallback connection as an option', async () => {
    svc.getPrerequisite.mockResolvedValue({
      hasConnection: true,
      connections: [
        { id: 'p1', name: 'Platform Gemini', provider: 'gemini', status: 'ACTIVE', isPlatform: true },
      ],
    });
    const { result } = renderHook(() => useAiPrerequisite());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.connections[0].isPlatform).toBe(true);
  });
});
