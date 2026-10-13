/**
 * Plan 20 AC-20-21/23 - `useIdeaSimilar`: available -> ready, available:false
 * or a failed request -> unavailable (never stuck loading), retry re-asks.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { IdeationRuntimeProvider } from '@/hooks/use-ideation-runtime';
import { ideationService } from '@/services/ideation-service';
import { useIdeaSimilar } from './use-idea-similar';

function wrapperFor(similar: (id: string) => Promise<unknown>) {
  const service = { ...ideationService, similar } as typeof ideationService;
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <IdeationRuntimeProvider
        runtime={{
          mode: 'operator',
          service,
          paths: { listHref: '/ideation/ideas', formHref: (id) => `/ideation/ideas/${id}`, newHref: '/ideation/ideas/new' },
        }}
      >
        {children}
      </IdeationRuntimeProvider>
    );
  };
}

describe('useIdeaSimilar', () => {
  it('maps available:false and errors to unavailable, and retry re-asks', async () => {
    const similar = vi
      .fn()
      .mockResolvedValueOnce({ available: false, ideas: [] })
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce({ available: true, ideas: [] });
    const { result } = renderHook(() => useIdeaSimilar('idea-1'), { wrapper: wrapperFor(similar) });
    await waitFor(() => expect(result.current.state.status).toBe('unavailable'));
    act(() => result.current.retry());
    await waitFor(() => expect(similar).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.state.status).toBe('unavailable'));
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.state).toEqual({ status: 'ready', ideas: [] }));
  });
});
