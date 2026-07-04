'use client';

import { useParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { VenueDetail } from './venue-detail';

export default function VenueDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <RequirePermission permission="venues.read">
      <VenueDetail venueId={params.id} />
    </RequirePermission>
  );
}
