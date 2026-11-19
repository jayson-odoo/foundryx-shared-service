'use client';

import { useCallback } from 'react';
import { useSession } from 'next-auth/react';
import { toast } from '@/lib/toast';
import { useFx } from '@/hooks/use-fx';

/** The signed-in person's name for "by Kay" on a done toast; undefined when
 *  there is no session around (a unit test, a sign-out in flight). */
function useActorName(): string | undefined {
  try {
    return useSession().data?.user?.name ?? undefined;
  } catch {
    return undefined;
  }
}

export interface AcDoneWords {
  what: string;
  forWhom?: string;
  howMany?: string;
}

/**
 * The AutoCount setup pages' "it happened" toast. Switch off: today's
 * `toast.success(plain)` with today's words. Switch on: the done toast that
 * says what, for whom, how many and by whom. No Undo is ever offered here:
 * none of these writes (connect, save, run, sync) has an API that reverses
 * it, and a pause or resume is its own visible action in the header.
 */
export function useAcDone(): (plain: string, words: AcDoneWords) => void {
  const fx = useFx();
  const byWhom = useActorName();
  return useCallback(
    (plain, words) => {
      if (fx) toast.fxDone({ ...words, byWhom });
      else toast.success(plain);
    },
    [fx, byWhom],
  );
}
