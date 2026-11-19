'use client';

import { useState } from 'react';
import { LoaderCircleIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { JobProgress } from '@/components/platform/autocount/job-progress';
import { DateRangePicker, type DateRangeValue } from '@/components/platform/date-range-picker';
import { dateKey } from '@/lib/datetime';
import type {
  DocFeedBackfillStartInput,
  DocFeedBackfillStatus,
  DocFeedKey,
  DocFeedMode,
} from '@/types/autocount';
import { docFeedLabel } from '../../components/autocount-meta';

// Mirrors `BACKFILL_FROM_DEFAULT` (doc_feed/constants.py); the feed row's
// `backfillFloor` wins when the backend sends it.
const DOC_FEED_BACKFILL_FROM = '2019-01-01';
// N5 (review round 1) - the backfill's own "today" is MYT (D6, fixed UTC+8,
// no DST), never the browser's local zone: before 08:00 MYT the browser's
// UTC "today" is still MYT's PREVIOUS day, and the backend refuses a `toDay`
// past its own MYT today (AC-14-63 range 422).
const MYT_ZONE = 'Asia/Kuala_Lumpur';

function nextDayKey(day: string): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

/** The earliest day a backfill may start. Once a live run from the floor (or
 * earlier) has completed, the backend 409s another live range starting on or
 * before the floor (doc_feed_service.start_backfill), so a live range then
 * starts the day after it. A run completed only from a LATER day (the old
 * 2023 floor) still allows one run from the floor. */
export function backfillMinDate({
  dryRun,
  floor,
  fullBackfillDoneAt,
  fullBackfillFromDay,
}: {
  dryRun: boolean;
  floor: string;
  fullBackfillDoneAt: string | null;
  fullBackfillFromDay: string | null;
}): string {
  if (dryRun || !fullBackfillDoneAt) return floor;
  if (fullBackfillFromDay && fullBackfillFromDay > floor) return floor;
  return nextDayKey(floor);
}

function mytTodayKey(): string {
  return dateKey(new Date(), { timeZone: MYT_ZONE }) ?? new Date().toISOString().slice(0, 10);
}

export interface DocFeedBackfillDialogProps {
  feed: DocFeedKey;
  /** A live (non dry run) backfill needs the feed in Push mode. */
  mode: DocFeedMode;
  /** Set once the full-history live backfill has completed. */
  fullBackfillDoneAt: string | null;
  /** The backfill range floor (YYYY-MM-DD); defaults to 2019-01-01. */
  backfillFloor?: string | null;
  /** Earliest from-day a completed live backfill ran from (YYYY-MM-DD). */
  fullBackfillFromDay?: string | null;
  /** `null` = no open/last backfill - the dialog offers to start one. */
  backfill: {
    status: DocFeedBackfillStatus;
    daysDone: number;
    daysTotal: number;
    dryRun: boolean;
  } | null;
  onClose: () => void;
  onStart: (input: DocFeedBackfillStartInput) => Promise<void>;
  onStop: () => Promise<void>;
}

/**
 * Backfill a document feed (AC-14-93, D13). While one is `running`/
 * `stopping` the dialog shows `JobProgress` in days with Stop; otherwise it
 * offers Dry run + a from/to range (defaulting to the floor .. today) and
 * Start.
 */
export function DocFeedBackfillDialog({
  feed,
  mode,
  fullBackfillDoneAt,
  backfillFloor,
  fullBackfillFromDay,
  backfill,
  onClose,
  onStart,
  onStop,
}: DocFeedBackfillDialogProps) {
  const floor = backfillFloor ?? DOC_FEED_BACKFILL_FROM;
  const [dryRunChoice, setDryRun] = useState(true);
  const [range, setRange] = useState<DateRangeValue>(() => ({
    preset: 'custom',
    from: floor,
    to: mytTodayKey(),
  }));
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);

  // Dry run is the only option a feed that is not in Push mode can start.
  const canGoLive = mode === 'push';
  const dryRun = canGoLive ? dryRunChoice : true;
  const minDate = backfillMinDate({
    dryRun,
    floor,
    fullBackfillDoneAt,
    fullBackfillFromDay: fullBackfillFromDay ?? null,
  });
  // Clamp `from` up to the floor, and `to` up to `from` (a live range of
  // exactly the floor day would otherwise end before it starts).
  const clampedFrom = range.from < minDate ? minDate : range.from;
  const effectiveRange: DateRangeValue =
    clampedFrom === range.from && range.to >= clampedFrom
      ? range
      : { ...range, from: clampedFrom, to: range.to < clampedFrom ? clampedFrom : range.to };

  const inFlight = backfill && (backfill.status === 'running' || backfill.status === 'stopping');

  async function submitStart() {
    setStarting(true);
    try {
      await onStart({ dryRun, fromDay: effectiveRange.from, toDay: effectiveRange.to });
    } finally {
      setStarting(false);
    }
  }

  async function submitStop() {
    setStopping(true);
    try {
      await onStop();
    } finally {
      setStopping(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Backfill - {docFeedLabel(feed)}</DialogTitle>
          <DialogDescription className="sr-only">Backfill {docFeedLabel(feed)}</DialogDescription>
        </DialogHeader>
        <DialogBody>
          {inFlight ? (
            <div className="flex flex-col gap-3">
              <JobProgress
                status={backfill.status === 'stopping' ? 'cancelling' : 'running'}
                stage={null}
                pagesDone={backfill.daysDone}
                pagesTotal={backfill.daysTotal}
                unit="days"
              />
              <div className="flex justify-end">
                <Button
                  variant="outline"
                  onClick={submitStop}
                  disabled={stopping || backfill.status === 'stopping'}
                  data-testid="backfill-stop"
                >
                  {stopping && <LoaderCircleIcon className="size-4 animate-spin" />}
                  Stop
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor="doc-feed-backfill-dry-run">Dry run</Label>
                <Switch
                  id="doc-feed-backfill-dry-run"
                  checked={dryRun}
                  onCheckedChange={setDryRun}
                  disabled={!canGoLive}
                  data-testid="backfill-dry-run-switch"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>Date range</Label>
                <DateRangePicker
                  value={effectiveRange}
                  onChange={setRange}
                  timeZone={MYT_ZONE}
                  minDate={minDate}
                  maxDate={mytTodayKey()}
                />
              </div>
            </div>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
          {!inFlight && (
            <Button onClick={submitStart} disabled={starting} data-testid="backfill-start">
              {starting && <LoaderCircleIcon className="size-4 animate-spin" />}
              Start
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
