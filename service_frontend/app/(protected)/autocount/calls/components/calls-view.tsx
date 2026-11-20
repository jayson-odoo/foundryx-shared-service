'use client';

import { useState } from 'react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { ResourceList } from '@/components/platform/resource-list';
import { StatusBadge } from '@/components/platform/status-badge';
import { useDatetime } from '@/hooks/use-datetime';
import type { AutocountCall, CallOutcome } from '@/types/autocount';
import { AC_CALL_OUTCOME_REGISTRY } from '../../components/autocount-meta';
import { useCallDetail } from './use-call-detail';
import { useCallsListConfig } from './use-calls-list-config';

/** A stored response body as readable text: pretty JSON when it parses, else as stored. */
function readable(body: string): string {
  try {
    return JSON.stringify(JSON.parse(body), null, 2);
  } catch {
    return body;
  }
}

function Block({ title, body }: { title: string; body: string | null }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="text-sm font-medium text-foreground">{title}</h3>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted p-3 text-xs text-foreground">
        {body ?? '-'}
      </pre>
    </section>
  );
}

function CallDialogBody({ callId }: { callId: string }) {
  const { detail, isLoading, error } = useCallDetail(callId);
  if (isLoading) return <Skeleton className="h-40 w-full" />;
  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (!detail) return null;
  return (
    <div className="flex flex-col gap-4">
      <Block
        title="Request"
        body={detail.requestJson === null || detail.requestJson === undefined ? null : JSON.stringify(detail.requestJson, null, 2)}
      />
      <Block title="Response" body={detail.responseBody === null ? null : readable(detail.responseBody)} />
    </div>
  );
}

/** The AutoCount calls list; a row opens a centred dialog with the request and the response. */
export function CallsView() {
  const [open, setOpen] = useState<AutocountCall | null>(null);
  const { formatDmyDateTime } = useDatetime();
  const config = useCallsListConfig({ onOpenCall: setOpen });

  return (
    <>
      <ResourceList config={config} />
      <Dialog open={open !== null} onOpenChange={(next) => !next && setOpen(null)}>
        <DialogContent className="sm:max-w-2xl">
          {open && (
            <>
              <DialogHeader>
                <DialogTitle className="flex flex-wrap items-center gap-2">
                  {open.method} {open.path}
                  <StatusBadge
                    status={open.outcome as CallOutcome}
                    registry={AC_CALL_OUTCOME_REGISTRY}
                    size="sm"
                  />
                </DialogTitle>
                <DialogDescription>{formatDmyDateTime(open.createdAt)}</DialogDescription>
              </DialogHeader>
              <DialogBody>
                <CallDialogBody callId={open.id} />
              </DialogBody>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
