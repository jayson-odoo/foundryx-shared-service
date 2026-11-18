'use client';

/**
 * Done screen (AC-64-17): what was connected, by whom and when, the test lead,
 * and the one thing still open. "Done" tells the opener and closes.
 */
import { CheckCircle2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ClampedText } from '@/components/platform/clamped-text';
import { useDatetime } from '@/hooks/use-datetime';
import type { WizardDone } from '@/types/lead-capture-wizard';

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:gap-3">
      <dt className="shrink-0 text-sm text-muted-foreground sm:w-36">{label}</dt>
      <dd className="min-w-0 text-sm text-foreground">
        <ClampedText text={value} lines={1} />
      </dd>
    </div>
  );
}

export function DoneScreen({ done, onDone }: { done: WizardDone; onDone: () => void }) {
  const { formatDmyDateTime } = useDatetime();
  const source = done.source;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <CheckCircle2 className="size-6 text-success" aria-hidden />
        <h1 className="font-heading text-lg font-semibold text-foreground">
          {source.pageName ?? source.name} is connected
        </h1>
      </div>
      <dl className="flex flex-col gap-2">
        <Row label="Channel" value="Facebook" />
        <Row label="Connected by" value={done.connectedBy ?? '-'} />
        <Row label="Connected on" value={done.connectedAt ? formatDmyDateTime(done.connectedAt) : '-'} />
        <Row label="Test lead received" value={done.testLeadAt ? formatDmyDateTime(done.testLeadAt) : '-'} />
        <Row label="Test lead form" value={done.testLeadFormName ?? '-'} />
        <Row label="Source" value={source.pageName ?? source.name} />
      </dl>
      {done.waitingForRealLead ? (
        <p className="rounded-md bg-muted px-3 py-2 text-sm text-foreground">Waiting for the first real lead</p>
      ) : null}
      <div>
        <Button type="button" onClick={onDone}>
          Done
        </Button>
      </div>
    </div>
  );
}
