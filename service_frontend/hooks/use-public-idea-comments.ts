'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { IdeaComment, IdeaCommentThread } from '@/types/ideation';
import { ApiError } from '@/lib/api-client';
import { toast } from '@/lib/toast';
import { publicIdeaStatusService } from '@/services/public-idea-status-service';
import { countLiveComments, groupCommentThreads } from './idea-comment-threads';

export interface UsePublicIdeaComments {
  threads: IdeaCommentThread[];
  count: number;
  loading: boolean;
  error: string | null;
  add: (body: string, parentId?: string) => Promise<void>;
}

const THROTTLED = 'Too many comments. Try again later.';

/**
 * Public status page comments (plan 19 section F, AC-19-33): no auth, the status
 * token is the capability. A 429 on post shows the throttle toast; any other
 * failure shows its message. Never throws into the render.
 */
export function usePublicIdeaComments(token: string): UsePublicIdeaComments {
  const [comments, setComments] = useState<IdeaComment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setComments(await publicIdeaStatusService.listComments(token));
      setError(null);
    } catch {
      setComments([]);
      setError('Could not load comments.');
    }
  }, [token]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    load().finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  const add = useCallback(
    async (body: string, parentId?: string) => {
      try {
        await publicIdeaStatusService.addComment(token, body, parentId);
      } catch (e) {
        if (e instanceof ApiError && e.status === 429) toast.error(THROTTLED);
        else
          toast.error(
            e instanceof Error && e.message
              ? e.message
              : 'Could not post the comment.',
          );
      }
      await load();
    },
    [token, load],
  );

  const threads = useMemo(() => groupCommentThreads(comments), [comments]);
  const count = useMemo(() => countLiveComments(comments), [comments]);

  return { threads, count, loading, error, add };
}
