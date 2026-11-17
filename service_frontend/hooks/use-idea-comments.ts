'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { IdeaAttachment, IdeaComment, IdeaCommentThread } from '@/types/ideation';
import { toast } from '@/lib/toast';
import { shrinkImage } from '@/lib/shrink-image';
import { useIdeationRuntime } from '@/hooks/use-ideation-runtime';
import { countLiveComments, groupCommentThreads } from './idea-comment-threads';

export interface UseIdeaComments {
  threads: IdeaCommentThread[];
  /** Live comments shown (a deleted placeholder is not counted). */
  count: number;
  loading: boolean;
  error: string | null;
  /** `files` are uploaded onto the new comment (the body may then be empty). */
  add: (body: string, parentId?: string, files?: File[]) => Promise<void>;
  edit: (commentId: string, body: string) => Promise<void>;
  remove: (commentId: string) => Promise<void>;
  /** Bytes of an uploaded file (auth-gated route), for thumbnails + preview. */
  fetchContent?: (attachment: IdeaAttachment) => Promise<Blob>;
}

const messageOf = (e: unknown, fallback: string): string =>
  e instanceof Error && e.message ? e.message : fallback;

/**
 * Comments for one idea (plan 19, AC-19-25): load + mutate through the runtime's
 * service (operator or embed), regroup into threads, reload after each write.
 * A service without comment support degrades to an empty list.
 */
export function useIdeaComments(ideaId: string): UseIdeaComments {
  const { service } = useIdeationRuntime();
  const [comments, setComments] = useState<IdeaComment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!service.listComments) {
      setComments([]);
      setError(null);
      return;
    }
    try {
      setComments(await service.listComments(ideaId));
      setError(null);
    } catch {
      setComments([]);
      setError('Could not load comments.');
    }
  }, [service, ideaId]);

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

  const mutate = useCallback(
    async (run: () => Promise<unknown> | undefined, failure: string) => {
      try {
        await run();
      } catch (e) {
        toast.error(messageOf(e, failure));
      }
      await load();
    },
    [load],
  );

  const add = useCallback(
    (body: string, parentId?: string, files: File[] = []) =>
      mutate(async () => {
        if (!service.addComment) return;
        const created =
          files.length > 0 && !body
            ? await service.addComment(ideaId, body, parentId, true)
            : await service.addComment(ideaId, body, parentId);
        if (files.length === 0 || !service.uploadAttachment) return;
        const failed: string[] = [];
        for (const file of files) {
          try {
            await service.uploadAttachment(ideaId, await shrinkImage(file), created.id);
          } catch {
            failed.push(file.name);
          }
        }
        // The comment exists either way: name what did not upload.
        if (failed.length > 0) toast.error(`Could not upload ${failed.join(', ')}.`);
      }, 'Could not post the comment.'),
    [mutate, service, ideaId],
  );
  const edit = useCallback(
    (commentId: string, body: string) =>
      mutate(
        () => service.editComment?.(ideaId, commentId, body),
        'Could not save the comment.',
      ),
    [mutate, service, ideaId],
  );
  const remove = useCallback(
    (commentId: string) =>
      mutate(
        () => service.deleteComment?.(ideaId, commentId),
        'Could not delete the comment.',
      ),
    [mutate, service, ideaId],
  );

  const threads = useMemo(() => groupCommentThreads(comments), [comments]);
  const count = useMemo(() => countLiveComments(comments), [comments]);

  const fetchContent = useMemo(
    () =>
      service.fetchAttachment
        ? (a: IdeaAttachment) => service.fetchAttachment!(a.contentPath ?? '')
        : undefined,
    [service],
  );

  return { threads, count, loading, error, add, edit, remove, fetchContent };
}
