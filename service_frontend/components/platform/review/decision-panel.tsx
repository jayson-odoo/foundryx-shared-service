'use client';

/**
 * Shared DECISION panel (plan sprint-4/06 slice 2, AC-06-07/45). One panel per
 * decision group. Identity-agnostic — the SAME component serves staff
 * `(protected)` and portal `(portal)`; the page supplies the service-bound
 * `actions.decide`. Shows the LIVE/partial average + a "ready" badge once
 * `requiredReviewCount` completed reviews exist (but Decide is enabled EARLY —
 * `ready` only labels the badge, never gates the button). Individual completed
 * reviews are expandable (decider-only — not exposed to authors or other
 * reviewers).
 *
 * Foolproof-UI: only valid decisions in the picker (Accept/Reject/Revisions);
 * feedback is optional, no how-to copy. The Submission noun relabels via
 * terminology (passed by the page).
 */
import { useState } from 'react';
import { ChevronDown, ChevronRight, LoaderCircleIcon } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { SearchSelect } from '@/components/platform/search-select';
import { EngineStatusBadge } from './engine-status-badge';
import type {
  DecisionItem,
  DecisionSurfaceActions,
  ReviewDecision,
} from '@/types/portal-review';

const DECISION_OPTIONS: { label: string; value: ReviewDecision }[] = [
  { label: 'Accept', value: 'ACCEPTED' },
  { label: 'Request revisions', value: 'REVISIONS' },
  { label: 'Reject', value: 'REJECTED' },
];

export interface DecisionPanelProps {
  item: DecisionItem;
  actions: DecisionSurfaceActions;
  submissionNoun?: string;
  reviewNoun?: string;
  /** Show the event/context label (AC-06-25) — true when unfiltered. */
  showContext?: boolean;
  /** Called with the updated group after a successful decision (refetch). */
  onDecided?: (updated: DecisionItem) => void;
}

export function DecisionPanel({
  item,
  actions,
  submissionNoun = 'Submission',
  reviewNoun = 'Review',
  showContext = false,
  onDecided,
}: DecisionPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [decision, setDecision] = useState<ReviewDecision | ''>('');
  const [feedback, setFeedback] = useState('');
  const [deciding, setDeciding] = useState(false);

  const decided = Boolean(item.decision);

  const submit = async () => {
    if (!decision) return;
    setDeciding(true);
    try {
      const updated = await actions.decide(
        item.groupId,
        decision,
        feedback.trim() || null,
      );
      toast.success('Decision recorded.');
      setDialogOpen(false);
      onDecided?.(updated);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not record the decision.');
    } finally {
      setDeciding(false);
    }
  };

  return (
    <div
      data-testid="decision-panel"
      className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate font-medium text-mono">{item.title}</h3>
            {showContext && item.contextLabel && (
              <Badge variant="secondary" appearance="light" size="sm" data-testid="row-context">
                {item.contextLabel}
              </Badge>
            )}
          </div>
          <p className="truncate text-xs text-muted-foreground">
            {item.reviewConfigurationName} · Revision {item.revisionNumber}
          </p>
        </div>
        <EngineStatusBadge
          statusKey={item.statusId}
          label={item.statusLabel}
          color={item.statusColor}
          size="sm"
        />
      </div>

      {/* Live average + ready badge. */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-baseline gap-1.5" data-testid="average-score">
          <span className="text-2xl font-semibold tabular-nums text-mono">
            {item.averageScore === null ? '—' : item.averageScore.toFixed(2)}
          </span>
          <span className="text-xs text-muted-foreground">avg</span>
        </div>
        <Badge
          variant={item.ready ? 'success' : 'secondary'}
          appearance="light"
          size="sm"
          data-testid="ready-badge"
        >
          {item.completedCount} / {item.requiredReviewCount} {item.ready ? '· Ready' : ''}
        </Badge>
        {decided && item.decision && (
          <Badge variant="primary" appearance="light" size="sm">
            {decisionLabel(item.decision)}
          </Badge>
        )}
      </div>

      {decided && item.feedbackText && (
        <p className="rounded-md bg-muted/50 px-3 py-2 text-sm text-foreground">
          {item.feedbackText}
        </p>
      )}

      {/* Individual completed reviews (decider-only). */}
      {item.reviews.length > 0 && (
        <div>
          <button
            type="button"
            className="flex items-center gap-1 text-sm font-medium text-foreground hover:text-primary"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
          >
            {expanded ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronRight className="size-4" />
            )}
            {item.reviews.length} {item.reviews.length === 1 ? reviewNoun.toLowerCase() : `${reviewNoun.toLowerCase()}s`}
          </button>
          {expanded && (
            <ul className="mt-2 flex flex-col gap-2" data-testid="individual-reviews">
              {item.reviews.map((r, i) => (
                <li
                  key={r.assignmentId}
                  className="rounded-md border border-border bg-background p-3"
                >
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <span className="text-xs font-medium text-muted-foreground">
                      {reviewNoun} {i + 1}
                    </span>
                    {r.score !== null && (
                      <Badge variant="info" appearance="light" size="sm">
                        Score {r.score}
                      </Badge>
                    )}
                  </div>
                  <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
                    {Object.entries(r.answers).map(([key, value]) => (
                      <div key={key} className="flex min-w-0 flex-col">
                        <dt className="truncate text-xs text-muted-foreground">{key}</dt>
                        <dd className="truncate text-foreground">{renderAnswer(value)}</dd>
                      </div>
                    ))}
                  </dl>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {!decided && (
        <div className="flex justify-end">
          <Button type="button" size="sm" onClick={() => setDialogOpen(true)}>
            Decide
          </Button>
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Decide</DialogTitle>
            <DialogDescription className="sr-only">
              Record a decision for this {submissionNoun.toLowerCase()}.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">Decision</label>
              <SearchSelect
                ariaLabel="Decision"
                placeholder="Select a decision"
                options={DECISION_OPTIONS}
                value={decision || undefined}
                onChange={(v) => setDecision(v as ReviewDecision)}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">Feedback</label>
              <Textarea
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                rows={4}
                placeholder="Optional"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={deciding}>
              Cancel
            </Button>
            <Button onClick={submit} disabled={!decision || deciding}>
              {deciding && <LoaderCircleIcon className="size-3.5 animate-spin" />}
              Record decision
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function decisionLabel(d: ReviewDecision): string {
  return DECISION_OPTIONS.find((o) => o.value === d)?.label ?? d;
}

function renderAnswer(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (Array.isArray(value)) return value.map((v) => String(v)).join(', ');
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
