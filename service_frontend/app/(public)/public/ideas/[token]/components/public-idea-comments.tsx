'use client';

/**
 * Plan 19 section F (AC-19-33/34): the status page's comment thread. Visitors
 * read and post (the author name comes from the submitter server side - there is
 * no name field); they can never edit or delete. A merged child keeps the thread
 * readable but hides posting. Data via `usePublicIdeaComments` (no component
 * fetch); presentation is the shared `IdeaCommentsView`.
 */
import { Card, CardContent } from '@/components/ui/card';
import { IdeaCommentsView } from '@/components/platform/idea-comments/idea-comments-view';
import { usePublicIdeaComments } from '@/hooks/use-public-idea-comments';

export interface PublicIdeaCommentsProps {
  token: string;
  mergedChild: boolean;
}

export function PublicIdeaComments({ token, mergedChild }: PublicIdeaCommentsProps) {
  const comments = usePublicIdeaComments(token);
  return (
    <Card>
      <CardContent className="pb-4 pt-0">
        <IdeaCommentsView
          threads={comments.threads}
          count={comments.count}
          loading={comments.loading}
          error={comments.error}
          canComment={!mergedChild}
          onAdd={comments.add}
        />
      </CardContent>
    </Card>
  );
}
