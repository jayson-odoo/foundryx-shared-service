import { act, renderHook } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { useHistory } from './use-history';

/** Drive the hook over a controlled value held in the same render. */
function useControlled<T>(initial: T) {
  const [value, setValue] = useState<T>(initial);
  const history = useHistory(value, setValue);
  return { value, setValue, history };
}

describe('useHistory', () => {
  it('set → undo → redo round-trips the value', () => {
    const { result } = renderHook(() => useControlled({ n: 0 }));

    act(() => result.current.history.set({ n: 1 }));
    expect(result.current.value).toEqual({ n: 1 });
    expect(result.current.history.canUndo).toBe(true);
    expect(result.current.history.canRedo).toBe(false);

    act(() => result.current.history.undo());
    expect(result.current.value).toEqual({ n: 0 });
    expect(result.current.history.canRedo).toBe(true);

    act(() => result.current.history.redo());
    expect(result.current.value).toEqual({ n: 1 });
  });

  it('a fresh set clears the redo stack', () => {
    const { result } = renderHook(() => useControlled({ n: 0 }));
    act(() => result.current.history.set({ n: 1 }));
    act(() => result.current.history.undo());
    expect(result.current.history.canRedo).toBe(true);
    act(() => result.current.history.set({ n: 2 }));
    expect(result.current.history.canRedo).toBe(false);
    expect(result.current.value).toEqual({ n: 2 });
  });

  it('an external value change (not via set) resets the timeline', () => {
    const { result } = renderHook(() => useControlled({ n: 0 }));
    act(() => result.current.history.set({ n: 1 }));
    expect(result.current.history.canUndo).toBe(true);
    // A load/discard swaps the value outside the hook → new editing session.
    act(() => result.current.setValue({ n: 9 }));
    expect(result.current.history.canUndo).toBe(false);
    expect(result.current.history.canRedo).toBe(false);
  });

  it('reset forgets the timeline (e.g. after a save commits the baseline)', () => {
    const { result } = renderHook(() => useControlled({ n: 0 }));
    act(() => result.current.history.set({ n: 1 }));
    act(() => result.current.history.reset());
    expect(result.current.history.canUndo).toBe(false);
    expect(result.current.value).toEqual({ n: 1 });
  });
});
