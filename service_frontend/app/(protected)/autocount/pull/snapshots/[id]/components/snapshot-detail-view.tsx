'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { LoaderCircleIcon, TriangleAlert } from 'lucide-react';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { OverflowPills } from '@/components/platform/overflow-pills';
import { StatusBadge } from '@/components/platform/status-badge';
import { JobProgress } from '@/components/platform/autocount/job-progress';
import { SqlPreviewGrid } from '@/components/platform/autocount/sql-preview-grid';
import { usePullSnapshotDetail, usePullSnapshotRows } from '@/hooks/use-autocount-pull';
import { useDatetime } from '@/hooks/use-datetime';
import { pullSnapshotRowsAsSqlPreview } from '@/lib/autocount-etl';
import {
  AC_PULL_PATH,
  AC_PULL_SNAPSHOT_STATUS_REGISTRY,
  entityLabel,
  pullEntityFromWire,
} from '../../../../components/autocount-meta';

export interface SnapshotDetailViewProps {
  id: string;
}

/** One labelled count (mirrors `preview-panel.tsx`'s `SummaryStat`). */
function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex min-w-[96px] flex-col rounded-md border border-border px-3 py-2">
      <span className="text-lg font-semibold text-foreground">{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

/**
 * Snapshot detail (sprint-5/10, AC-10-49) - header facts, per-entity
 * metadata blocks, the excluded-row list, and the first page of rows in the
 * EXISTING preview grid (`SqlPreviewGrid`, reused via an adapter). Polls
 * while `building`.
 */
export function SnapshotDetailView({ id }: SnapshotDetailViewProps) {
  const { formatDateTime } = useDatetime();
  const { state } = usePullSnapshotDetail(id);
  const rows = usePullSnapshotRows(id);

  const snapshot = state.status === 'ready' ? state.snapshot : null;
  useEffect(() => {
    if (snapshot?.status === 'ready') void rows.run(0, 1000);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshot?.status, snapshot?.id]);

  return (
    <Container width="fluid">
      <PageHeader
        title="Snapshot"
        crumbs={[{ label: 'AutoCount' }, { label: 'Pull', href: AC_PULL_PATH }, { label: 'Snapshot' }]}
      />

      {state.status === 'loading' && (
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      )}

      {state.status === 'notFound' && (
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Snapshot not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={AC_PULL_PATH}>Back to Pull</Link>
          </Button>
        </div>
      )}

      {state.status === 'error' && (
        <Alert variant="destructive" appearance="light">
          <AlertIcon>
            <TriangleAlert />
          </AlertIcon>
          <AlertTitle>{state.message}</AlertTitle>
        </Alert>
      )}

      {snapshot && (
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader>
              <CardHeading>
                <CardTitle className="flex flex-wrap items-center gap-2">
                  {entityLabel(pullEntityFromWire(snapshot.entityType))}
                  <StatusBadge status={snapshot.status} registry={AC_PULL_SNAPSHOT_STATUS_REGISTRY} />
                  <Badge variant="secondary" appearance="light" size="sm">
                    {snapshot.companyCode}
                  </Badge>
                </CardTitle>
              </CardHeading>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              {snapshot.status === 'building' && (
                <div data-testid="snapshot-building">
                  {snapshot.progress ? (
                    // AC-11-43 - the SAME running-state component the preview
                    // job uses (`JobProgress`, extended with no `onCancel` -
                    // a build's own Cancel is BL-SS-248, not this plan).
                    <JobProgress
                      status="running"
                      stage={snapshot.progress.stage}
                      pagesDone={snapshot.progress.pagesDone}
                      pagesTotal={snapshot.progress.pagesTotal}
                    />
                  ) : (
                    <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
                      <LoaderCircleIcon className="size-4 animate-spin" />
                      Building…
                    </div>
                  )}
                </div>
              )}

              {snapshot.status === 'failed' && snapshot.error && (
                <Alert variant="destructive" appearance="light" data-testid="snapshot-failed">
                  <AlertIcon>
                    <TriangleAlert />
                  </AlertIcon>
                  <AlertTitle>{snapshot.error.message}</AlertTitle>
                </Alert>
              )}

              {snapshot.status === 'ready' && (
                <>
                  <div className="flex flex-wrap gap-2">
                    <Stat label="Records" value={snapshot.recordCount.toLocaleString('en-US')} />
                    <Stat label="Complete" value={snapshot.complete ? 'Yes' : 'No'} />
                    <Stat label="Built" value={snapshot.extractedAt ? formatDateTime(snapshot.extractedAt) : '-'} />
                    <Stat label="Expires" value={snapshot.expiresAt ? formatDateTime(snapshot.expiresAt) : '-'} />
                  </div>

                  {snapshot.contentHash && (
                    <div className="flex flex-col gap-1">
                      <span className="text-xs text-muted-foreground">Content hash</span>
                      <ClampedText
                        text={snapshot.contentHash}
                        lines={1}
                        className="max-w-md font-mono text-xs"
                      />
                    </div>
                  )}

                  {snapshot.entityType === 'product' && (
                    <div className="flex flex-wrap gap-2" data-testid="snapshot-product-counters">
                      <Stat label="Zero list price" value={snapshot.zeroListPriceCount ?? 0} />
                      <Stat label="Negative list price (clamped)" value={snapshot.negativeListPriceCount ?? 0} />
                      <Stat label="Enrich miss" value={snapshot.enrichMissCount ?? 0} />
                    </div>
                  )}

                  {snapshot.entityType === 'stock_balance' && (
                    <div className="flex flex-col gap-3" data-testid="snapshot-stock-counters">
                      <div className="flex flex-wrap gap-2">
                        <Stat label="Zero pairs" value={snapshot.zeroPairs ?? 0} />
                        <Stat label="Negative pairs" value={snapshot.negativePairs ?? 0} />
                        <Stat label="Fractional pairs" value={snapshot.fractionalPairs ?? 0} />
                        <Stat label="Excluded (nonzero)" value={snapshot.excludedNonzeroCount ?? 0} />
                      </div>
                      {(snapshot.negativePairList ?? []).length > 0 && (
                        <div className="flex flex-col gap-1">
                          <span className="text-xs text-muted-foreground">Negative pairs</span>
                          <OverflowPills
                            items={snapshot.negativePairList ?? []}
                            keyFor={(p) => `${p.item_code}|${p.location_code}`}
                            renderPill={(p) => (
                              <Badge variant="destructive" appearance="light" size="sm">
                                {p.item_code} · {p.location_code} · {p.qty}
                              </Badge>
                            )}
                          />
                        </div>
                      )}
                    </div>
                  )}

                  {snapshot.excludedRows.length > 0 && (
                    <div className="flex flex-col gap-1.5" data-testid="snapshot-excluded-rows">
                      <span className="text-xs text-muted-foreground">
                        Excluded rows ({snapshot.excludedCount})
                      </span>
                      <div className="flex flex-col gap-1">
                        {snapshot.excludedRows.map((row, i) => (
                          <div
                            key={i}
                            className="flex flex-wrap items-center gap-2 rounded-md border border-border px-3 py-1.5 text-xs"
                          >
                            <Badge variant="warning" appearance="light" size="sm">
                              {String(row.reason)}
                            </Badge>
                            <ClampedText
                              text={Object.entries(row)
                                .filter(([k]) => k !== 'reason')
                                .map(([k, v]) => `${k}: ${String(v)}`)
                                .join(' · ')}
                              lines={1}
                              className="min-w-0 flex-1 font-mono text-muted-foreground"
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <SqlPreviewGrid
                    state={
                      rows.state.status === 'success'
                        ? { status: 'success', preview: pullSnapshotRowsAsSqlPreview(rows.state.page) }
                        : rows.state
                    }
                  />
                </>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </Container>
  );
}
