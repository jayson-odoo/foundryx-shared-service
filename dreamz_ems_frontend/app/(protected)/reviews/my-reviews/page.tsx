'use client';

import { Fragment } from 'react';
import { useRouter } from 'next/navigation';
import { LoaderCircleIcon } from 'lucide-react';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ReviewQueue } from '@/components/platform/review';
import { useTerminology } from '@/hooks/use-terminology';
import { useStaffReviewQueue } from '@/hooks/use-staff-review';

/** Staff My Reviews queue (plan sprint-4/06 slice 2, AC-06-46) — user-kind
 * actors grade on the staff app. Gated `reviews.grade`. Opens the SAME shared
 * two-pane the portal uses. */
export default function StaffMyReviewsPage() {
  const router = useRouter();
  const { label, labelPlural } = useTerminology();
  const { data, loading, error } = useStaffReviewQueue();

  return (
    <RequirePermission permission="reviews.grade">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle text={`My ${labelPlural('review')}`} />
              <ToolbarDescription>
                {labelPlural('review')} assigned to you.
              </ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          {loading ? (
            <div className="flex items-center justify-center py-24 text-muted-foreground">
              <LoaderCircleIcon className="size-6 animate-spin" />
            </div>
          ) : error ? (
            <p className="py-12 text-center text-sm text-destructive">{error}</p>
          ) : (
            <ReviewQueue
              reviews={data}
              reviewNoun={label('review')}
              onOpen={(id) => router.push(`/reviews/my-reviews/${id}`)}
            />
          )}
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
