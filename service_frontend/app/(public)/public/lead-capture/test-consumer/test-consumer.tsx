'use client';

import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ClampedText } from '@/components/platform/clamped-text';
import { useDatetime } from '@/hooks/use-datetime';
import { useLeadCaptureTestConsumer } from '@/hooks/use-lead-capture-test-consumer';
import { SOURCE_STATUS_REGISTRY } from '@/app/(protected)/lead-capture/sources/components/source-status';

function Value({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 flex-col">
      <span className="text-xs text-muted-foreground">{label}</span>
      <ClampedText text={value} lines={1} className="text-sm text-foreground" />
    </div>
  );
}

/** Stand-in product page for the Lead Capture hand test. */
export function TestConsumer() {
  const { snapshot, loading, error, lastMessage, connect, refresh } = useLeadCaptureTestConsumer();
  const { formatDmyDateTime } = useDatetime();

  return (
    <main className="flex min-h-screen justify-center bg-background px-4 py-6">
      <div className="flex w-full max-w-2xl flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="font-heading text-lg font-semibold text-foreground">Test CRM</h1>
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" onClick={() => void refresh()} disabled={loading}>
              <RefreshCw aria-hidden />
              Refresh leads
            </Button>
            <Button type="button" onClick={() => void connect()}>
              Connect a source
            </Button>
          </div>
        </div>

        {error ? <p className="rounded-md border border-destructive/40 p-3 text-sm text-foreground">{error}</p> : null}
        {lastMessage ? (
          <p className="rounded-md bg-muted px-3 py-2 text-sm text-foreground" data-testid="last-message">
            Received: {lastMessage.type}
          </p>
        ) : null}

        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-medium text-muted-foreground">Sources</h2>
          {(snapshot?.sources ?? []).length === 0 ? <p className="text-sm text-muted-foreground">-</p> : null}
          {(snapshot?.sources ?? []).map((s) => (
            <div key={s.id} className="grid grid-cols-2 gap-2 rounded-lg border border-border p-3 sm:grid-cols-3">
              <Value label="Page" value={s.pageName ?? s.name} />
              <Value label="Status" value={SOURCE_STATUS_REGISTRY[s.status]?.label ?? s.status} />
              <div className="col-span-2 flex items-end sm:col-span-1 sm:justify-end">
                <Button type="button" variant="outline" size="sm" onClick={() => void connect(s.id)}>
                  Reconnect
                </Button>
              </div>
            </div>
          ))}
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-medium text-muted-foreground">Leads received</h2>
          {(snapshot?.leads ?? []).length === 0 ? <p className="text-sm text-muted-foreground">-</p> : null}
          {(snapshot?.leads ?? []).map((lead) => (
            <div key={lead.id} className="grid grid-cols-2 gap-2 rounded-lg border border-border p-3 sm:grid-cols-3">
              <Value label="Received" value={formatDmyDateTime(lead.receivedAt)} />
              <Value label="Name" value={lead.fields.name ?? '-'} />
              <Value label="Email" value={lead.fields.email ?? '-'} />
              <Value label="Phone" value={lead.fields.phone ?? '-'} />
              <Value label="Form" value={lead.formName ?? '-'} />
              <Value label="Test lead" value={lead.isTest ? 'Yes' : 'No'} />
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}
