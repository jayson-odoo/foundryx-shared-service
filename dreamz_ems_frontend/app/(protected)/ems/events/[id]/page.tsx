'use client';

import { useParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { EventDetail } from './event-detail';

/** Event detail route — Participants + the event's eligibility-flow editor. */
export default function EventDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <RequirePermission permission="projects.read">
      <EventDetail projectId={params.id} />
    </RequirePermission>
  );
}
