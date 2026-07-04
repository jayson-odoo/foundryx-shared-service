import { Suspense } from 'react';
import { MySubmissionsClient } from './my-submissions-client';

/** Portal My Submissions surface (plan sprint-4/06 slice 2, AC-06-43). */
export default function PortalSubmissionsPage() {
  return (
    <Suspense fallback={null}>
      <MySubmissionsClient />
    </Suspense>
  );
}
