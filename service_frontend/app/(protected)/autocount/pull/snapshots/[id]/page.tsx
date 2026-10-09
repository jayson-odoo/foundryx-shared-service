'use client';

import { use } from 'react';
import { RequirePermission } from '@/components/common/require-permission';
import { AC_PULL_READ } from '../../../components/autocount-meta';
import { SnapshotDetailView } from './components/snapshot-detail-view';

export default function AutocountPullSnapshotPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  return (
    <RequirePermission permission={AC_PULL_READ}>
      <SnapshotDetailView id={id} />
    </RequirePermission>
  );
}
