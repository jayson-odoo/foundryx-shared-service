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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { JobProgress } from '@/components/platform/autocount/job-progress';
import type { DocFeedBackfillStartInput, DocFeedBackfillStatus, DocFeedKey } from '@/types/autocount';
import { docFeedLabel } from '../../components/autocount-meta';

const DOC_FEED_BACKFILL_FROM = '2023-01-01';

function todayKey(): string {
  return new Date().toISOString().slice(0, 10);
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
  const [fromDay, setFromDay] = useState(DOC_FEED_BACKFILL_FROM);
  const [toDay, setToDay] = useState(todayKey);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);

  const inFlight = backfill && (backfill.status === 'running' || backfill.status === 'stopping');

  async function submitStart() {
    setStarting(true);
    try {
      await onStart({ dryRun, fromDay, toDay });
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
          <DialogDescription>Re-pull this feed's history, one day at a time.</DialogDescription>
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
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="doc-feed-backfill-from">From</Label>
                  <Input
                    id="doc-feed-backfill-from"
                    type="date"
                    value={fromDay}
                    min={DOC_FEED_BACKFILL_FROM}
                    max={toDay}
                    onChange={(event) => setFromDay(event.target.value)}
                    data-testid="backfill-from-day"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="doc-feed-backfill-to">To</Label>
                  <Input
                    id="doc-feed-backfill-to"
                    type="date"
                    value={toDay}
                    min={fromDay}
                    max={todayKey()}
                    onChange={(event) => setToDay(event.target.value)}
                    data-testid="backfill-to-day"
                  />
                </div>
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
