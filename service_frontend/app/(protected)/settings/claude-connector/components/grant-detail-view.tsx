'use client';

import { useMemo } from 'react';
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
import type { ConnectorActivity, ConnectorGrant } from '@/types/connector';
import { CONNECTOR_PATH, CONNECTOR_STATUS_REGISTRY } from './connector-status';
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
  const { formatDateTime } = useDatetime();
  const calls = activity?.calls ?? [];
  const events = activity?.events ?? [];
  const callsConfig = useConnectorActivityListConfig(calls);

  return (
    <div className="flex flex-col gap-6 py-2">
      <ResourceList config={callsConfig} />
      {events.length > 0 && (
        <ul className="flex flex-col gap-2">
          {events.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium capitalize">{e.type}</span>
              <span className="text-muted-foreground">{formatDateTime(e.at)}</span>
              {e.detail && <span className="text-muted-foreground">{e.detail}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DetailsTab({ grant }: { grant: ConnectorGrant }) {
  const { formatDateTime } = useDatetime();
  return (
    <div className="flex flex-col gap-4 py-2">
      {grant.userEmail && <Row label="Email">{grant.userEmail}</Row>}
      <Row label="Product">{grant.product}</Row>
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

  const config = useMemo<ResourceFormConfig<ConnectorGrant> | null>(() => {
    if (!grant) return null;
    return {
      breadcrumb: [
        { label: 'Settings' },
        { label: 'Claude connector', href: CONNECTOR_PATH },
        { label: 'Grant' },
      ],
      backHref: CONNECTOR_PATH,
      title: grant.userName,
      subtitle: grant.product,
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
    };
  }, [grant, activity, actions, reload]);

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
