'use client';

import { use } from 'react';
import { RequirePermission } from '@/components/common/require-permission';
import { AC_SYNC_READ } from '../../components/autocount-meta';
import { ReviewView } from './components/review-view';

export default function AutocountReviewPage({
  params,
  searchParams,
}: {
  params: Promise<{ jobId: string }>;
  searchParams: Promise<{ from?: string }>;
}) {
  const { jobId } = use(params);
  const { from } = use(searchParams);

  return (
    <RequirePermission permission={AC_SYNC_READ}>
      <ReviewView jobId={jobId} from={from} />
    </RequirePermission>
  );
}
