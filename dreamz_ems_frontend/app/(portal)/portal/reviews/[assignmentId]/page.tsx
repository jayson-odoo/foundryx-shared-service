import { Suspense } from 'react';
import { ReviewGradeClient } from './review-grade-client';

/** Portal two-pane grade page (plan sprint-4/06 slice 2, AC-06-05/44/48). */
export default function PortalReviewGradePage() {
  return (
    <Suspense fallback={null}>
      <ReviewGradeClient />
    </Suspense>
  );
}
