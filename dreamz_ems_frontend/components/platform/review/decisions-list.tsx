'use client';

/**
 * Shared Decisions LIST (plan sprint-4/06 slice 2, AC-06-45). One
 * `DecisionPanel` per group. Identity-agnostic — staff + portal both render it;
 * the page supplies the service-bound `actions` + an `onDecided` to refetch.
 */
import { DecisionPanel } from './decision-panel';
import type { DecisionItem, DecisionSurfaceActions } from '@/types/portal-review';

export interface DecisionsListProps {
  items: DecisionItem[];
  actions: DecisionSurfaceActions;
  onDecided?: () => void;
  submissionNoun?: string;
  reviewNoun?: string;
  /** Show the per-row event/context label (AC-06-25) — true when the global
   * event filter is OFF. */
  showContext?: boolean;
}

export function DecisionsList({
  items,
  actions,
  onDecided,
  submissionNoun,
  reviewNoun,
  showContext = false,
}: DecisionsListProps) {
  if (items.length === 0) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        Nothing to decide.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3" data-testid="decisions-list">
      {items.map((item) => (
        <DecisionPanel
          key={item.groupId}
          item={item}
          actions={actions}
          submissionNoun={submissionNoun}
          reviewNoun={reviewNoun}
          showContext={showContext}
          onDecided={() => onDecided?.()}
        />
      ))}
    </div>
  );
}
