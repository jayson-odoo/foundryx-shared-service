'use client';

import { LoaderCircleIcon, TriangleAlert } from 'lucide-react';
import { Alert, AlertDescription, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardContent,
  CardHeader,
  CardHeading,
  CardTitle,
} from '@/components/ui/card';
import { ClampedText } from '@/components/platform/clamped-text';
import {
  partitionPredictions,
  type AutocountPreview,
  type AutocountPrediction,
} from '@/types/autocount';
import { PredictionDiff } from './prediction-diff';

/** One labelled count in the summary strip. */
function SummaryStat({
  label,
  value,
  tone = 'default',
}: {
  label: string;
  value: number;
  tone?: 'default' | 'warning' | 'destructive';
}) {
  return (
    <div
      className="flex min-w-[64px] flex-col rounded-md border border-border px-3 py-2"
      data-testid={`preview-stat-${label.toLowerCase()}`}
    >
      <span
        className={
          tone === 'destructive'
            ? 'text-lg font-semibold text-destructive'
            : tone === 'warning'
              ? 'text-lg font-semibold text-warning'
              : 'text-lg font-semibold text-foreground'
        }
      >
        {value}
      </span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

function OverwriteCard({ prediction }: { prediction: AutocountPrediction }) {
  return (
    <Card data-testid={`preview-overwrite-${prediction.sourceRef}`}>
      <CardHeader className="flex-col items-start gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
        <CardHeading className="min-w-0">
          <CardTitle className="min-w-0">
            <ClampedText
              text={prediction.sourceRef}
              lines={1}
              className="text-sm font-semibold text-foreground"
            />
          </CardTitle>
        </CardHeading>
        <Badge variant="warning" appearance="light" size="sm">
          {prediction.outcome === 'created' ? 'Creates' : 'Overwrites'}
        </Badge>
      </CardHeader>
      <CardContent className="py-3">
        <PredictionDiff diff={prediction.diff} />
      </CardContent>
    </Card>
  );
}

function FailedCard({ prediction }: { prediction: AutocountPrediction }) {
  const messages = Object.entries(prediction.errors ?? {});
  return (
    <Card data-testid={`preview-failed-${prediction.sourceRef}`}>
      <CardHeader className="flex-col items-start gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
        <CardTitle className="text-sm font-semibold text-foreground">
          {prediction.sourceRef}
        </CardTitle>
        <Badge variant="destructive" appearance="light" size="sm">
          Would fail
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-1 py-3">
        {messages.length === 0 ? (
          <p className="text-sm text-destructive">This record would be rejected.</p>
        ) : (
          messages.map(([field, message]) => (
            <p key={field} className="text-sm text-destructive">
              {[field, typeof message === 'string' ? message : JSON.stringify(message)]
                .filter(Boolean)
                .join(' · ')}
            </p>
          ))
        )}
      </CardContent>
    </Card>
  );
}

export interface PreviewPanelProps {
  preview: AutocountPreview | null;
  isLoading: boolean;
  /** Set when the dry run itself failed — approval is blocked upstream. */
  error: string | null;
  /** Whether a preview has been requested yet. */
  hasRun: boolean;
}

/**
 * The dry-run verdict at the overwrite gate (AC-14-20/22/26). Shows the
 * consumer's summary counts, then the rows that would OVERWRITE live data
 * prominently (blankings tinted destructive by `PredictionDiff`), and collapses
 * safe creates into a single count so overwrites are never buried under them.
 *
 * "Preview" is a prediction, not a delivery — approving is the separate act
 * (AC-14-41). Copy here is labels + one-line status only (foolproof-UI).
 */
export function PreviewPanel({ preview, isLoading, error, hasRun }: PreviewPanelProps) {
  if (isLoading) {
    return (
      <div
        className="flex items-center gap-2 py-6 text-sm text-muted-foreground"
        data-testid="preview-loading"
      >
        <LoaderCircleIcon className="size-4 animate-spin" />
        Running dry run…
      </div>
    );
  }

  if (error) {
    return (
      <Alert variant="destructive" appearance="light" data-testid="preview-error">
        <AlertIcon>
          <TriangleAlert />
        </AlertIcon>
        <AlertTitle>Dry run failed</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (!hasRun || !preview) return null;

  if (!preview.previewable) {
    return (
      <Alert variant="secondary" appearance="light" data-testid="preview-unavailable">
        <AlertIcon>
          <TriangleAlert />
        </AlertIcon>
        <AlertTitle>Nothing to preview</AlertTitle>
        <AlertDescription>{preview.reason}</AlertDescription>
      </Alert>
    );
  }

  const { summary, predictions } = preview;
  const { overwrites, created, otherUpdates, failed } = partitionPredictions(predictions);
  const safeCount = created.length + otherUpdates.length;

  return (
    <div className="flex flex-col gap-4" data-testid="preview-panel">
      <div className="flex flex-wrap gap-2">
        <SummaryStat label="Total" value={summary.total} />
        <SummaryStat label="Created" value={summary.created} />
        <SummaryStat label="Updated" value={summary.updated} />
        <SummaryStat
          label="Failed"
          value={summary.failed}
          tone={summary.failed > 0 ? 'destructive' : 'default'}
        />
        {summary.retryable > 0 && (
          <SummaryStat label="Retryable" value={summary.retryable} tone="warning" />
        )}
      </div>

      {failed.length > 0 && (
        <div className="flex flex-col gap-2" data-testid="preview-failed-list">
          <span className="text-sm font-semibold text-destructive">
            {failed.length} record{failed.length === 1 ? '' : 's'} would fail
          </span>
          <div className="flex max-h-[40vh] flex-col gap-2 overflow-y-auto">
            {failed.map((p) => (
              <FailedCard key={p.sourceRef} prediction={p} />
            ))}
          </div>
        </div>
      )}

      {overwrites.length > 0 ? (
        <div className="flex flex-col gap-2" data-testid="preview-overwrites">
          <span className="text-sm font-semibold text-foreground">
            {overwrites.length} record{overwrites.length === 1 ? '' : 's'} would overwrite
            live data
          </span>
          <div className="flex max-h-[55vh] flex-col gap-3 overflow-y-auto pr-1">
            {overwrites.map((p) => (
              <OverwriteCard key={p.sourceRef} prediction={p} />
            ))}
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground" data-testid="preview-no-overwrites">
          No live data would be overwritten.
        </p>
      )}

      {safeCount > 0 && (
        <p className="text-sm text-muted-foreground" data-testid="preview-safe-summary">
          {created.length > 0 && (
            <>
              {created.length} new record{created.length === 1 ? '' : 's'}
            </>
          )}
          {created.length > 0 && otherUpdates.length > 0 && ' · '}
          {otherUpdates.length > 0 && (
            <>
              {otherUpdates.length} update{otherUpdates.length === 1 ? '' : 's'} with no
              value change
            </>
          )}
          .
        </p>
      )}
    </div>
  );
}
