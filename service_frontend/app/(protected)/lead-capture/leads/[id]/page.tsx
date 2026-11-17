'use client';

/**
 * One captured lead (plan 64 AC-64-53): mapped fields, form answers,
 * attribution and every delivery attempt with Redeliver. The raw platform
 * payload stays server-side (AC-64-71).
 */
import { use, useCallback } from 'react';
import { useSearchParams } from 'next/navigation';
import { RotateCw } from 'lucide-react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { ClampedText } from '@/components/platform/clamped-text';
import { PageHeader } from '@/components/platform/page-header';
import { RecordNav } from '@/components/platform/resource-form/record-nav';
import { buildListNav } from '@/lib/list-context';
import { leadCaptureSourcesService } from '@/services/lead-capture-sources-service';
import type { ListQuery } from '@/types/resource';
import { leadHref } from '../components/use-leads-list-config';
import { StatusBadge } from '@/components/platform/status-badge';
import { useCan } from '@/hooks/use-can';
import { useDatetime } from '@/hooks/use-datetime';
import { useLeadDetail } from '@/hooks/use-lead-capture-sources';
import type { LeadBody } from '@/types/lead-capture-sources';
import { DELIVERY_STATUS_REGISTRY, PLATFORM_LABELS } from '../../sources/components/source-status';

function leadTitle(lead: LeadBody): string {
  return lead.fields.name || lead.fields.email || lead.fields.phone || lead.formName || 'Lead';
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5 py-1.5 sm:flex-row sm:gap-4">
      <dt className="shrink-0 text-sm text-muted-foreground sm:w-48">
        <ClampedText text={label} lines={1} />
      </dt>
      <dd className="min-w-0 text-sm text-foreground">
        <ClampedText text={value} lines={2} />
      </dd>
    </div>
  );
}

function answerValue(value: string | string[] | null | undefined): string {
  if (Array.isArray(value)) return value.join(', ') || '-';
  return value || '-';
}

const ATTRIBUTION_LABELS: Record<string, string> = {
  campaignId: 'Campaign',
  campaignName: 'Campaign name',
  adsetId: 'Ad set',
  adsetName: 'Ad set name',
  adId: 'Ad',
  adName: 'Ad name',
  formId: 'Form',
  pageId: 'Page',
};

export default function LeadDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { detail, error, loading, redeliver, redelivering, reload } = useLeadDetail(id);
  const { formatDmyDateTime } = useDatetime();
  const { can } = useCan();
  const sourceId = useSearchParams().get('source');
  const fetchAt = useCallback(
    async (query: ListQuery, index: number) => {
      const res = await leadCaptureSourcesService.listLeads({ ...query, page: index, pageSize: 1 }, sourceId);
      return { recordId: res.data[0]?.id ?? null, total: res.total };
    },
    [sourceId],
  );
  const buildHref = useCallback(
    (recordId: string, ctx: string, index: number) => buildListNav(leadHref(recordId, sourceId), { ctx, i: index }),
    [sourceId],
  );

  return (
    <RequirePermission permission="lead_capture.view">
      <Container width="fluid">
        <div className="flex flex-col gap-4 pb-8">
          <PageHeader
            title={detail ? leadTitle(detail.lead) : 'Lead'}
            crumbs={[{ label: 'Lead Capture' }, { label: 'Leads', href: '/lead-capture/leads' }, { label: detail ? leadTitle(detail.lead) : 'Lead' }]}
            description={detail?.lead.isTest ? 'Test lead' : undefined}
            actions={<RecordNav fetchAt={fetchAt} buildHref={buildHref} />}
          />
          {loading && !detail ? (
            <div className="flex flex-col gap-3">
              <Skeleton className="h-7 w-64" />
              <Skeleton className="h-40 w-full" />
            </div>
          ) : error ? (
            <div className="flex flex-col items-start gap-3 rounded-lg border border-border p-4">
              <p className="text-sm text-foreground">{error}</p>
              <Button type="button" onClick={reload}>
                Try again
              </Button>
            </div>
          ) : detail ? (
            <>
              <div className="grid gap-4 lg:grid-cols-2">
                <Card>
                  <CardHeader>
                    <CardTitle>Lead</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <dl className="divide-y divide-border">
                      <Row label="Received" value={formatDmyDateTime(detail.lead.receivedAt)} />
                      <Row label="Source" value={detail.lead.sourceName} />
                      <Row label="Channel" value={PLATFORM_LABELS[detail.lead.platform] ?? detail.lead.platform} />
                      <Row label="Form" value={detail.lead.formName ?? '-'} />
                      {Object.entries(detail.lead.fields).map(([key, value]) => (
                        <Row key={key} label={key} value={value ?? '-'} />
                      ))}
                    </dl>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle>Form answers</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <dl className="divide-y divide-border">
                      {detail.lead.answers.length === 0 ? <Row label="Answers" value="-" /> : null}
                      {detail.lead.answers.map((a, i) => (
                        <Row key={`${a.key ?? i}`} label={a.label ?? a.key ?? '-'} value={answerValue(a.value)} />
                      ))}
                    </dl>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle>Attribution</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <dl className="divide-y divide-border">
                      {Object.entries(detail.lead.attribution).filter(([, v]) => v).length === 0 ? (
                        <Row label="Ad" value="-" />
                      ) : null}
                      {Object.entries(detail.lead.attribution)
                        .filter(([, v]) => v)
                        .map(([key, value]) => (
                          <Row key={key} label={ATTRIBUTION_LABELS[key] ?? key} value={String(value)} />
                        ))}
                    </dl>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle>Deliveries</CardTitle>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-3">
                    {detail.deliveries.length === 0 ? (
                      <p className="text-sm text-muted-foreground">No receiver is set up.</p>
                    ) : null}
                    {detail.deliveries.map((d) => (
                      <div key={d.id} className="flex flex-col gap-2 rounded-lg border border-border p-3">
                        <div className="flex items-center justify-between gap-2">
                          <StatusBadge status={d.status} registry={DELIVERY_STATUS_REGISTRY} />
                          {can('lead_capture.manage') ? (
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              disabled={redelivering === d.id}
                              onClick={() => void redeliver(d.id)}
                            >
                              <RotateCw aria-hidden />
                              Redeliver
                            </Button>
                          ) : null}
                        </div>
                        <dl>
                          <Row label="Receiver" value={d.endpointUrl ?? '-'} />
                          <Row label="Event" value={d.event} />
                          <Row label="Attempts" value={String(d.attempt)} />
                          <Row label="Last attempt" value={d.lastAttemptAt ? formatDmyDateTime(d.lastAttemptAt) : '-'} />
                          <Row label="Last answer" value={d.lastStatusCode ? String(d.lastStatusCode) : '-'} />
                          <Row label="Last error" value={d.lastError ?? '-'} />
                          <Row label="Next attempt" value={d.nextAttemptAt ? formatDmyDateTime(d.nextAttemptAt) : '-'} />
                        </dl>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              </div>
            </>
          ) : null}
        </div>
      </Container>
    </RequirePermission>
  );
}
