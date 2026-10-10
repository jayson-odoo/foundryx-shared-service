'use client';

import { useCallback, useMemo } from 'react';
import Link from 'next/link';
import { useForm } from 'react-hook-form';
import { Activity, Info, LoaderCircleIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { Label } from '@/components/ui/label';
import { ResourceList } from '@/components/platform/resource-list';
import { ResourceForm, type ResourceFormConfig } from '@/components/platform/resource-form';
import { StatusBadge } from '@/components/platform/status-badge';
import { useDatetime } from '@/hooks/use-datetime';
import { buildListNav } from '@/lib/list-context';
import { listGrants } from '@/services/connector-service';
import type { ListQuery } from '@/types/resource';
import type { ConnectorActivity, ConnectorGrant, ConnectorGrantStatus } from '@/types/connector';
import { CONNECTOR_PATH, CONNECTOR_STATUS_REGISTRY, connectorGrantPath } from './connector-status';
import { useConnectorActivityListConfig } from './use-connector-activity-list-config';
import { useConnectorGrant } from './use-connector-grant';
import { useConnectorGrantActions } from './use-connector-grant-list-config';

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1 md:grid-cols-[200px_1fr] md:items-center md:gap-4">
      <Label className="text-sm text-muted-foreground">{label}</Label>
      <div className="text-sm">{children}</div>
    </div>
  );
}

function ActivityTab({ activity }: { activity: ConnectorActivity | null }) {
  const config = useConnectorActivityListConfig(activity);
  return (
    <div className="py-2">
      <ResourceList config={config} hideHeader />
    </div>
  );
}

function DetailsTab({ grant }: { grant: ConnectorGrant }) {
  const { formatDateTime } = useDatetime();
  return (
    <div className="flex flex-col gap-4 py-2">
      {grant.userEmail && <Row label="Email">{grant.userEmail}</Row>}
      <Row label="Product">{grant.productName}</Row>
      <Row label="Product user id">
        <code className="text-xs">{grant.productUserId}</code>
      </Row>
      <Row label="Client">{grant.clientName}</Row>
      <Row label="Status">
        <StatusBadge status={grant.status} registry={CONNECTOR_STATUS_REGISTRY} size="sm" />
      </Row>
      <Row label="Granted">{formatDateTime(grant.grantedAt)}</Row>
      {grant.consentedAt && <Row label="Consented">{formatDateTime(grant.consentedAt)}</Row>}
      <Row label="Last used">{grant.lastUsedAt ? formatDateTime(grant.lastUsedAt) : '-'}</Row>
      <Row label="Calls (30 d)">{grant.calls30d}</Row>
      {grant.revokedReason && <Row label="Revoked reason">{grant.revokedReason}</Row>}
    </div>
  );
}

/** Read-only grant detail (no Edit toggle): Details + Activity tabs. */
export function GrantDetailView({ grantId }: { grantId: string }) {
  const { grant, activity, isLoading, reload } = useConnectorGrant(grantId);
  const actions = useConnectorGrantActions();
  const form = useForm({ mode: 'onTouched' });

  // Shell record-nav (carried list query): the neighbour at an index of that query.
  const fetchRecordAt = useCallback(
    (query: ListQuery, index: number) =>
      listGrants({
        status: (query.segment as ConnectorGrantStatus | undefined) ?? 'active',
        search: query.search || undefined,
        page: index,
        pageSize: 1,
      }).then((r) => ({ recordId: r.data[0]?.id ?? null, total: r.total })),
    [],
  );
  const buildRecordHref = useCallback(
    (recordId: string, ctx: string, index: number) =>
      buildListNav(connectorGrantPath(recordId), { ctx, i: index }),
    [],
  );

  const config = useMemo<ResourceFormConfig<ConnectorGrant> | null>(() => {
    if (!grant) return null;
    return {
      breadcrumb: [
        { label: 'Settings' },
        { label: 'Claude connector', href: CONNECTOR_PATH },
        { label: grant.userName },
      ],
      backHref: CONNECTOR_PATH,
      title: grant.userName,
      subtitle: grant.productName,
      tabs: [
        { id: 'details', label: 'Details', icon: Info, render: () => <DetailsTab grant={grant} /> },
        {
          id: 'activity',
          label: 'Activity',
          icon: Activity,
          render: () => <ActivityTab activity={activity} />,
        },
      ],
      initialTabId: 'details',
      actions,
      actionRows: [grant],
      editable: false,
      isDirty: false,
      onSave: () => true,
      onCancel: reload,
      onReload: reload,
      recordNav: { fetchAt: fetchRecordAt, buildHref: buildRecordHref },
    };
  }, [grant, activity, actions, reload, fetchRecordAt, buildRecordHref]);

  if (isLoading) {
    return (
      <div className="mx-auto w-full px-4 lg:px-6">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </div>
    );
  }

  if (!grant || !config) {
    return (
      <div className="mx-auto w-full px-4 lg:px-6">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Grant not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={CONNECTOR_PATH}>Back to Claude connector</Link>
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full px-4 lg:px-6">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>
    </div>
  );
}
