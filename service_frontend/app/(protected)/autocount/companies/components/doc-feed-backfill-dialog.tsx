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
import type { DocFeedBackfillStartInput, DocFeedBackfillStatus, DocFeedKey } from '@/types/autocount';
import { docFeedLabel } from '../../components/autocount-meta';

const DOC_FEED_BACKFILL_FROM = '2023-01-01';
// N5 (review round 1) - the backfill's own "today" is MYT (D6, fixed UTC+8,
// no DST), never the browser's local zone: before 08:00 MYT the browser's
// UTC "today" is still MYT's PREVIOUS day, and the backend refuses a `toDay`
// past its own MYT today (AC-14-63 range 422).
const MYT_ZONE = 'Asia/Kuala_Lumpur';

function mytTodayKey(): string {
  return dateKey(new Date(), { timeZone: MYT_ZONE }) ?? new Date().toISOString().slice(0, 10);
}

export interface DocFeedBackfillDialogProps {
  feed: DocFeedKey;
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
 * offers Dry run + a from/to range (defaulting to 2023-01-01 .. today) and
 * Start.
 */
export function DocFeedBackfillDialog({
  feed,
  backfill,
  onClose,
  onStart,
  onStop,
}: DocFeedBackfillDialogProps) {
  const [dryRun, setDryRun] = useState(true);
  const [range, setRange] = useState<DateRangeValue>(() => ({
    preset: 'custom',
    from: DOC_FEED_BACKFILL_FROM,
    to: mytTodayKey(),
  }));
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);

  const inFlight = backfill && (backfill.status === 'running' || backfill.status === 'stopping');

  async function submitStart() {
    setStarting(true);
    try {
      await onStart({ dryRun, fromDay: range.from, toDay: range.to });
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
                  data-testid="backfill-dry-run-switch"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>Date range</Label>
                <DateRangePicker
                  value={range}
                  onChange={setRange}
                  timeZone={MYT_ZONE}
                  minDate={DOC_FEED_BACKFILL_FROM}
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
