import { Suspense } from 'react';
import { MyReviewsClient } from './my-reviews-client';

/** Portal My Reviews queue (plan sprint-4/06 slice 2, AC-06-44). */
export default function PortalReviewsPage() {
  return (
    <Suspense fallback={null}>
      <MyReviewsClient />
    </Suspense>
  );
}
