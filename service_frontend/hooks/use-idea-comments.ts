'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { IdeaAttachment, IdeaComment, IdeaCommentThread } from '@/types/ideation';
import { toast } from '@/lib/toast';
import { uploadInOrder, type CommentPostResult } from '@/lib/upload-files';
import { useIdeationRuntime } from '@/hooks/use-ideation-runtime';
import { countLiveComments, groupCommentThreads } from './idea-comment-threads';

export interface UseIdeaComments {
  threads: IdeaCommentThread[];
  /** Live comments shown (a deleted placeholder is not counted). */
  count: number;
  loading: boolean;
  error: string | null;
  /** `files` are uploaded onto the new comment (the body may then be empty). */
  add: (body: string, parentId?: string, files?: File[]) => Promise<CommentPostResult | undefined>;
  /** Retry only the files that failed against a comment that already exists. */
  retryUploads: (commentId: string, files: File[]) => Promise<File[]>;
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
    async (body: string, parentId?: string, files: File[] = []) => {
      let result: CommentPostResult | undefined;
      try {
        if (!service.addComment) return undefined;
        const created =
          files.length > 0 && !body
            ? await service.addComment(ideaId, body, parentId, true)
            : await service.addComment(ideaId, body, parentId);
        const upload = service.uploadAttachment?.bind(service);
        // The comment exists either way: report what did not upload.
        const failed =
          files.length > 0 && upload
            ? await uploadInOrder(files, (file) => upload(ideaId, file, created.id))
            : [];
        result = { commentId: created.id, failed };
      } catch (e) {
        toast.error(messageOf(e, 'Could not post the comment.'));
      }
      await load();
      return result;
    },
    [load, service, ideaId],
  );
  const retryUploads = useCallback(
    async (commentId: string, files: File[]) => {
      const upload = service.uploadAttachment?.bind(service);
      const failed = upload ? await uploadInOrder(files, (file) => upload(ideaId, file, commentId)) : files;
      await load();
      return failed;
    },
    [load, service, ideaId],
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

  return { threads, count, loading, error, add, retryUploads, edit, remove, fetchContent };
}
