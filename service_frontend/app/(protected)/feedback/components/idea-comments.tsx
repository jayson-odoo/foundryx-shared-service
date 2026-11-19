'use client';

import { toast } from '@/lib/toast';
import { useFx } from '@/hooks/use-fx';
import { useCan } from '@/hooks/use-can';
import { useIdeaComments } from '@/hooks/use-idea-comments';
import { useIdeationRuntime } from '@/hooks/use-ideation-runtime';
import { IdeaCommentsView } from '@/components/platform/idea-comments/idea-comments-view';

export interface IdeaCommentsProps {
  ideaId: string;
  /** A merged child's thread is read-only (AC-19-08/24). */
  mergedChild?: boolean;
  /** Whether the viewer may post. The idea form resolves this once (it already
   * reads the session) and passes it down; omitted = resolved here from the
   * session (operator) or always allowed (embed, the backend scopes it). */
  canComment?: boolean;
}

function CommentsBody({
  ideaId,
  canComment,
}: {
  ideaId: string;
  canComment: boolean;
}) {
  const comments = useIdeaComments(ideaId);
  // Foundryx UIUX switch only (never in the public portal or the embed, which
  // sit outside the switch): a done toast for a posted comment (an edit or delete reports no result to toast on). Requests are the same in both looks.
  const fx = useFx();
  const onAdd: typeof comments.add = async (...args) => {
    const result = await comments.add(...args);
    if (fx && result) toast.fxDone({ what: args[1] ? 'Reply posted' : 'Comment posted', byWhom: 'you' });
    return result;
  };
  return (
    <IdeaCommentsView
      threads={comments.threads}
      count={comments.count}
      loading={comments.loading}
      error={comments.error}
      canComment={canComment}
      visibleToSubmitter
      allowAttachments
      onRetryUploads={comments.retryUploads}
      fetchAttachment={comments.fetchContent}
      onAdd={fx ? onAdd : comments.add}
      onEdit={comments.edit}
      onRemove={comments.remove}
    />
  );
}

function SessionGatedComments({
  ideaId,
  mergedChild,
}: {
  ideaId: string;
  mergedChild: boolean;
}) {
  const { mode } = useIdeationRuntime();
  const { can } = useCan();
  const canComment =
    !mergedChild && (mode === 'embed' || can('ideation.ideas.comment'));
  return <CommentsBody ideaId={ideaId} canComment={canComment} />;
}

/**
 * The idea page's Comments section (plan 19, AC-19-21..25), operator AND embed:
 * data via `useIdeaComments` (the runtime's service), presentation via the shared
 * `IdeaCommentsView`. The composer shows to an embed user always and to an
 * operator holding `ideation.ideas.comment`; never on a merged child.
 */
export function IdeaComments({
  ideaId,
  mergedChild = false,
  canComment,
}: IdeaCommentsProps) {
  if (canComment !== undefined) {
    return (
      <CommentsBody ideaId={ideaId} canComment={canComment && !mergedChild} />
    );
  }
  return <SessionGatedComments ideaId={ideaId} mergedChild={mergedChild} />;
}
