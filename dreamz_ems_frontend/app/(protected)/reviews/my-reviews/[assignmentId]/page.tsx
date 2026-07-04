'use client';

import { Fragment } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, LoaderCircleIcon } from 'lucide-react';
import {
  Toolbar,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { RequirePermission } from '@/components/common/require-permission';
import { ReviewTwoPaneView } from '@/components/platform/review';
import { apiFetchBlob } from '@/lib/api-client';
import { useTerminology } from '@/hooks/use-terminology';
import { useReviewTwoPane } from '@/hooks/use-review-two-pane';
import { useStaffReviewActions } from '@/hooks/use-staff-review';

/** Staff two-pane grade page (AC-06-46/05/48) — consumes the SAME shared
 * `ReviewTwoPaneView` as the portal; only the service differs. */
export default function StaffReviewGradePage() {
  const params = useParams();
  const router = useRouter();
  const assignmentId = String(params.assignmentId);
  const { label } = useTerminology();
  const actions = useStaffReviewActions();
  const { data, loading, error } = useReviewTwoPane(actions, assignmentId);

  return (
    <RequirePermission permission="reviews.grade">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle text={label('review')} />
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <Button
            variant="ghost"
            size="sm"
            className="mb-4"
            onClick={() => router.push('/reviews/my-reviews')}
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
              fileFetcher={apiFetchBlob}
              onSubmitted={() => router.push('/reviews/my-reviews')}
            />
          )}
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
