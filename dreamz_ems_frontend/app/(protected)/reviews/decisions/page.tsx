'use client';

import { Fragment } from 'react';
import { LoaderCircleIcon } from 'lucide-react';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { DecisionsList } from '@/components/platform/review';
import { useTerminology } from '@/hooks/use-terminology';
import { useStaffDecisionActions, useStaffDecisions } from '@/hooks/use-staff-review';

/** Staff Decisions (AC-06-46/45) — user-kind deciders, gated `reviews.decide`.
 * Consumes the SAME shared `DecisionsList`/`DecisionPanel` as the portal. */
export default function StaffDecisionsPage() {
  const { label } = useTerminology();
  const { data, loading, error, reload } = useStaffDecisions();
  const actions = useStaffDecisionActions();

  return (
    <RequirePermission permission="reviews.decide">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle text="Decisions" />
              <ToolbarDescription>
                Submissions awaiting your decision.
              </ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          {loading ? (
            <div className="flex items-center justify-center py-24 text-muted-foreground">
              <LoaderCircleIcon className="size-6 animate-spin" />
            </div>
          ) : error ? (
            <p className="py-12 text-center text-sm text-destructive">{error}</p>
          ) : (
            <DecisionsList
              items={data}
              actions={actions}
              onDecided={reload}
              submissionNoun={label('submission')}
              reviewNoun={label('review')}
            />
          )}
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
