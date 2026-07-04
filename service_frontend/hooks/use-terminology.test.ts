import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TermLabels, TerminologyMap } from '@/types/terminology';

const svc = {
  getTerminology: vi.fn(),
  getCatalog: vi.fn(),
  setTerm: vi.fn(),
  resetTerm: vi.fn(),
};
vi.mock('@/services/terminology-service', () => ({
  get terminologyService() {
    return svc;
  },
}));

import {
  humanize,
  refreshTerminology,
  useTerminology,
  useTerminologyAdmin,
} from './use-terminology';

const MAP: TerminologyMap = {
  form: { singular: 'Survey', plural: 'Surveys' },
  workflow: { singular: 'Workflow', plural: 'Workflows' },
};

beforeEach(() => {
  vi.clearAllMocks();
  svc.getTerminology.mockResolvedValue(MAP);
});

describe('humanize (never-blank fallback, D7)', () => {
  it('title-cases a snake/dot/dash key', () => {
    expect(humanize('event_type')).toBe('Event Type');
    expect(humanize('project.participant')).toBe('Project Participant');
    expect(humanize('role')).toBe('Role');
  });
});

describe('useTerminology resolver', () => {
  it('resolves override > default, plural, and count-aware t()', async () => {
    await act(async () => {
      await refreshTerminology();
    });
    const { result } = renderHook(() => useTerminology());
    await waitFor(() => expect(result.current.ready).toBe(true));

    expect(result.current.label('form')).toBe('Survey');
    expect(result.current.labelPlural('form')).toBe('Surveys');
    expect(result.current.t('form', 1)).toBe('Survey');
    expect(result.current.t('form', 3)).toBe('Surveys');
  });

  it('falls back to a humanized key when unregistered (never blank)', async () => {
    await act(async () => {
      await refreshTerminology();
    });
    const { result } = renderHook(() => useTerminology());
    await waitFor(() => expect(result.current.ready).toBe(true));

    expect(result.current.label('mystery_thing')).toBe('Mystery Thing');
    expect(result.current.labelPlural('mystery_thing')).toBe('Mystery Things');
  });
});

describe('useTerminologyAdmin refetch after setTerm (D6)', () => {
  it('setTerm calls the service then refreshes the merged map', async () => {
    const labels: TermLabels = { singular: 'Poll', plural: 'Polls' };
    svc.setTerm.mockResolvedValue(labels);
    svc.getCatalog.mockResolvedValue([]);

    const { result } = renderHook(() => useTerminologyAdmin());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // After setTerm the store refetches → new label resolves.
    svc.getTerminology.mockResolvedValue({
      ...MAP,
      form: { singular: 'Poll', plural: 'Polls' },
    });
    await act(async () => {
      await result.current.setTerm('form', labels);
    });

    expect(svc.setTerm).toHaveBeenCalledWith('form', labels);
    const term = renderHook(() => useTerminology());
    await waitFor(() => expect(term.result.current.label('form')).toBe('Poll'));
  });
});
