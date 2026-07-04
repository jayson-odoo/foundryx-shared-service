'use client';

import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, LoaderCircleIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ReviewTwoPaneView } from '@/components/platform/review';
import { portalApiFetchBlob } from '@/lib/portal-api-client';
import { usePortalTerminology } from '@/hooks/use-portal-terminology';
import { useReviewTwoPane } from '@/hooks/use-review-two-pane';
import {
  usePortalReviewActions,
  usePortalSessionReady,
} from '@/hooks/use-portal-review';
import { PortalPageShell } from '../../portal-page-shell';

/** Portal two-pane grade (AC-06-05/44/48) — read-only submission ‖ review form
 * with draft-save/resume, consuming the SAME shared `ReviewTwoPaneView` as
 * staff. */
export function ReviewGradeClient() {
  const params = useParams();
  const router = useRouter();
  const assignmentId = String(params.assignmentId);
  const { label } = usePortalTerminology();
  const actions = usePortalReviewActions();
  const ready = usePortalSessionReady();
  const { data, loading, error } = useReviewTwoPane(actions, assignmentId, ready);

  return (
    <PortalPageShell surfaceKey="my_reviews" title={label('review')}>
      <Button
        variant="ghost"
        size="sm"
        className="mb-4"
        onClick={() => router.push('/portal/reviews')}
      >
        <ArrowLeft className="size-3.5" /> Back to queue
      </Button>

      {loading ? (
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      ) : error || !data ? (
        <p className="py-12 text-center text-sm text-destructive">
          {error ?? 'This review is not available.'}
        </p>
      ) : (
        <ReviewTwoPaneView
          data={data}
          actions={actions}
          submissionNoun={label('submission')}
          reviewNoun={label('review')}
          fileFetcher={(path) => portalApiFetchBlob(path)}
          onSubmitted={() => router.push('/portal/reviews')}
        />
      )}
    </PortalPageShell>
  );
}
