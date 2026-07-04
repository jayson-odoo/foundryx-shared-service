'use client';

import { useParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { ProfileDetail } from './profile-detail';

/** Profile detail route — view/edit fields + tier-1 status change. */
export default function ProfileDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <RequirePermission permission="profiles.read">
      <ProfileDetail profileId={params.id} />
    </RequirePermission>
  );
}
