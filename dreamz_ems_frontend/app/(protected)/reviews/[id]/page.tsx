'use client';

import { useParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { ReviewConfigDetail } from './review-config-detail';

/** Review-process detail route — Details + Roles (AC-06-38). */
export default function ReviewConfigDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <RequirePermission permission="reviews.read">
      <ReviewConfigDetail id={params.id} />
    </RequirePermission>
  );
}
