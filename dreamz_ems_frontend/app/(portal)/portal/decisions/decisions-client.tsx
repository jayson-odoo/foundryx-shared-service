'use client';

import { LoaderCircleIcon } from 'lucide-react';
import { DecisionsList } from '@/components/platform/review';
import { usePortalTerminology } from '@/hooks/use-portal-terminology';
import {
  usePortalDecisionActions,
  usePortalDecisions,
} from '@/hooks/use-portal-review';
import { usePortalFilter } from '@/providers/portal-filter-provider';
import { PortalPageShell } from '../portal-page-shell';

/** Portal Decisions (AC-06-45) — live average + ready badge + early decide,
 * via the SAME shared `DecisionsList`/`DecisionPanel` as staff. */
export function DecisionsClient() {
  const { label } = usePortalTerminology();
  const { data, loading, error, reload } = usePortalDecisions();
  const actions = usePortalDecisionActions();
  const { activeContextKey } = usePortalFilter();
  const showContext = !activeContextKey;

  return (
    <PortalPageShell surfaceKey="decisions" title="Decisions">
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
          showContext={showContext}
        />
      )}
    </PortalPageShell>
  );
}
