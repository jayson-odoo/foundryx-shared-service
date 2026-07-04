import { Suspense } from 'react';
import { DecisionsClient } from './decisions-client';

/** Portal Decisions surface (plan sprint-4/06 slice 2, AC-06-45). */
export default function PortalDecisionsPage() {
  return (
    <Suspense fallback={null}>
      <DecisionsClient />
    </Suspense>
  );
}
