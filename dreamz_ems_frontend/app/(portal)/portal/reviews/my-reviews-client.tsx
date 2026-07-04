'use client';

import { useRouter } from 'next/navigation';
import { LoaderCircleIcon } from 'lucide-react';
import { ReviewQueue } from '@/components/platform/review';
import { usePortalTerminology } from '@/hooks/use-portal-terminology';
import { usePortalReviewQueue } from '@/hooks/use-portal-review';
import { usePortalFilter } from '@/providers/portal-filter-provider';
import { PortalPageShell } from '../portal-page-shell';

/** Portal My Reviews queue (AC-06-44) — opens the two-pane grade page per row. */
export function MyReviewsClient() {
  const router = useRouter();
  const { label, labelPlural } = usePortalTerminology();
  const { data, loading, error } = usePortalReviewQueue();
  const { activeContextKey } = usePortalFilter();
  const showContext = !activeContextKey;

  return (
    <PortalPageShell surfaceKey="my_reviews" title={`My ${labelPlural('review')}`}>
      {loading ? (
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      ) : error ? (
        <p className="py-12 text-center text-sm text-destructive">{error}</p>
      ) : (
        <ReviewQueue
          reviews={data}
          reviewNoun={label('review')}
          showContext={showContext}
          onOpen={(id) => router.push(`/portal/reviews/${id}`)}
        />
      )}
    </PortalPageShell>
  );
}
