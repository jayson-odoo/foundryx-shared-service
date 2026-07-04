'use client';

import { Fragment, useCallback, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { RequirePermission } from '@/components/common/require-permission';
import { reviewConfigService } from '@/services/review-config-service';
import type { ReviewConfig } from '@/types/review';
import { useReviewListConfig } from './use-review-list-config';
import { CreateReviewDialog } from './create-review-dialog';

/** Standalone core "Review processes" admin (AC-06-38) — list/create/edit
 * `review_configurations` over any form, on the Resource shell. Core, no module
 * tag (the engine operates on any form_submission). */
export default function ReviewsPage() {
  const router = useRouter();
  const [creating, setCreating] = useState(false);
  const [nonce, setNonce] = useState(0);

  const onCreate = useCallback(() => setCreating(true), []);
  const onEdit = useCallback((row: ReviewConfig) => router.push(`/reviews/${row.id}`), [router]);
  const onDelete = useCallback((row: ReviewConfig) => reviewConfigService.remove(row.id), []);

  const ctx = useMemo(() => ({ onCreate, onEdit, onDelete }), [onCreate, onEdit, onDelete]);
  const config = useReviewListConfig(ctx);

  return (
    <RequirePermission permission="reviews.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle text="Review processes" />
              <ToolbarDescription>
                Review and approval over any form submission.
              </ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <ResourceList key={nonce} config={config} />
        </Container>
        {creating && (
          <CreateReviewDialog
            onClose={() => setCreating(false)}
            onCreated={(id) => {
              setCreating(false);
              setNonce((n) => n + 1);
              router.push(`/reviews/${id}`);
            }}
          />
        )}
      </Fragment>
    </RequirePermission>
  );
}
