import { renderHook, waitFor, act } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { GrillState } from '@/types/grill';

const svc = {
  state: vi.fn(),
  open: vi.fn(),
  turn: vi.fn(),
  generate: vi.fn(),
};
vi.mock('@/services/grill-service', () => ({
  get grillService() {
    return svc;
  },
}));

import { useGrill } from './use-grill';

const FIELDS = [
  { key: 'problem_statement', label: 'Problem statement' },
  { key: 'business_goal', label: 'Business goal' },
];

function state(overrides: Partial<GrillState> = {}): GrillState {
  return {
    ready: true,
    warning: null,
    agentName: 'Ideation grill',
    fields: FIELDS,
    messages: [],
    coveredFields: [],
    capturedSummary: {},
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  svc.state.mockResolvedValue(state());
  svc.open.mockResolvedValue({
    replyText: 'Greeting?',
    coveredFields: ['problem_statement'],
    capturedSummary: { problem_statement: 'Exports are slow' },
    generateSignal: false,
  });
});

describe('useGrill (AC-BI-22/29)', () => {
  it('loads readiness, fields and derives the missing set', async () => {
    const { result } = renderHook(() => useGrill('br-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.ready).toBe(true);
    expect(result.current.fields).toHaveLength(2);
    expect(result.current.missingFields.map((f) => f.key)).toEqual([
      'problem_statement',
      'business_goal',
    ]);
  });

  it('surfaces the prerequisite warning when no connection is configured (AC-BI-11)', async () => {
    svc.state.mockResolvedValue(state({ ready: false, warning: 'No AI connection configured.' }));
    const { result } = renderHook(() => useGrill('br-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.ready).toBe(false);
    expect(result.current.warning).toBe('No AI connection configured.');
  });

  it('sends a turn and re-syncs the transcript + coverage', async () => {
    svc.turn.mockResolvedValue({
      replyText: 'Next?',
      coveredFields: ['problem_statement'],
      capturedSummary: { problem_statement: 'Exports are slow' },
      generateSignal: false,
    });
    svc.state
      .mockResolvedValueOnce(state())
      .mockResolvedValueOnce(
        state({
          messages: [
            { id: 'u', role: 'user', content: 'hi', coveredFields: [], createdAt: 'x' },
            {
              id: 'a',
              role: 'assistant',
              content: 'Next?',
              coveredFields: ['problem_statement'],
              createdAt: 'x',
            },
          ],
          coveredFields: ['problem_statement'],
        }),
      );
    const { result } = renderHook(() => useGrill('br-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.sendTurn('hi');
    });
    expect(svc.turn).toHaveBeenCalledWith('br-1', 'hi');
    expect(result.current.coveredFields).toEqual(['problem_statement']);
    expect(result.current.missingFields.map((f) => f.key)).toEqual(['business_goal']);
  });

  it('updates the running captured summary from a turn (AC-BI-24c)', async () => {
    svc.turn.mockResolvedValue({
      replyText: 'Next?',
      coveredFields: ['problem_statement', 'business_goal'],
      capturedSummary: {
        problem_statement: 'Exports time out on big accounts',
        business_goal: 'Cut month-end manual work',
      },
      generateSignal: false,
    });
    const { result } = renderHook(() => useGrill('br-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.sendTurn('CS cannot export');
    });
    expect(result.current.capturedSummary).toEqual({
      problem_statement: 'Exports time out on big accounts',
      business_goal: 'Cut month-end manual work',
    });
  });

  it('fires Generate exactly once when the turn carries generateSignal (AC-BI-24c)', async () => {
    svc.turn.mockResolvedValue({
      replyText: 'On it.',
      coveredFields: ['problem_statement'],
      capturedSummary: { problem_statement: 'Exports are slow' },
      generateSignal: true,
    });
    const onGenerated = vi.fn();
    const br = { id: 'br-1', status: 'draft', answers: {} };
    svc.generate.mockResolvedValue({ status: 'ok', br, answers: {}, fieldErrors: {} });
    const { result } = renderHook(() => useGrill('br-1', { onGenerated }));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.sendTurn('generate it');
    });
    await waitFor(() => expect(svc.generate).toHaveBeenCalledTimes(1));
    expect(onGenerated).toHaveBeenCalledWith(br);
  });

  it('does NOT fire Generate on a normal turn (generateSignal false)', async () => {
    svc.turn.mockResolvedValue({
      replyText: 'What is the success metric?',
      coveredFields: ['problem_statement'],
      capturedSummary: { problem_statement: 'Exports are slow' },
      generateSignal: false,
    });
    const { result } = renderHook(() => useGrill('br-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.sendTurn('It is about exports');
    });
    expect(svc.generate).not.toHaveBeenCalled();
  });

  it('rolls the optimistic turn back on a provider error, keeping the transcript consistent (AC-BI-23)', async () => {
    svc.turn.mockRejectedValue(new Error('provider down'));
    const { result } = renderHook(() => useGrill('br-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.sendTurn('hi');
    });
    expect(result.current.error).toBe('provider down');
    expect(result.current.messages).toHaveLength(0); // optimistic turn rolled back
  });

  it('calls onGenerated with the refreshed BR on a successful Generate', async () => {
    const onGenerated = vi.fn();
    const br = { id: 'br-1', status: 'draft', answers: { problem_statement: 'p' } };
    svc.generate.mockResolvedValue({ status: 'ok', br, answers: {}, fieldErrors: {} });
    const { result } = renderHook(() => useGrill('br-1', { onGenerated }));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.generate();
    });
    expect(onGenerated).toHaveBeenCalledWith(br);
  });

  describe('auto-open (AC-BI-29b)', () => {
    it('fires the opening turn EXACTLY once when ready + empty + autoOpen', async () => {
      const { rerender } = renderHook(() => useGrill('br-1', { autoOpen: true }));
      await waitFor(() => expect(svc.open).toHaveBeenCalledTimes(1));
      expect(svc.open).toHaveBeenCalledWith('br-1');
      // A re-render must NOT re-fire the opening turn.
      rerender();
      rerender();
      await new Promise((r) => setTimeout(r, 0));
      expect(svc.open).toHaveBeenCalledTimes(1);
    });

    it('does NOT auto-open when the transcript already has messages', async () => {
      svc.state.mockResolvedValue(
        state({
          messages: [
            { id: 'a', role: 'assistant', content: 'hi', coveredFields: [], createdAt: 'x' },
          ],
        }),
      );
      const { result } = renderHook(() => useGrill('br-1', { autoOpen: true }));
      await waitFor(() => expect(result.current.isLoading).toBe(false));
      await new Promise((r) => setTimeout(r, 0));
      expect(svc.open).not.toHaveBeenCalled();
    });

    it('does NOT auto-open when the grill is not ready (no connection)', async () => {
      svc.state.mockResolvedValue(state({ ready: false, warning: 'No AI connection configured.' }));
      const { result } = renderHook(() => useGrill('br-1', { autoOpen: true }));
      await waitFor(() => expect(result.current.isLoading).toBe(false));
      await new Promise((r) => setTimeout(r, 0));
      expect(svc.open).not.toHaveBeenCalled();
    });

    it('does NOT auto-open when autoOpen is false (no linked ideas)', async () => {
      const { result } = renderHook(() => useGrill('br-1'));
      await waitFor(() => expect(result.current.isLoading).toBe(false));
      await new Promise((r) => setTimeout(r, 0));
      expect(svc.open).not.toHaveBeenCalled();
    });
  });

  it('surfaces field errors when Generate needs review (AC-BI-25)', async () => {
    svc.generate.mockResolvedValue({
      status: 'needs_review',
      br: null,
      answers: {},
      fieldErrors: { success_metric: 'Enter a valid value.' },
    });
    const { result } = renderHook(() => useGrill('br-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.generate();
    });
    expect(result.current.fieldErrors.success_metric).toBe('Enter a valid value.');
    expect(result.current.error).toBeTruthy();
  });
});
