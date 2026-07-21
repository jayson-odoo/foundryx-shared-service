'use client';

import { useCallback, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { History, Info, LoaderCircleIcon, RefreshCw } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Form } from '@/components/ui/form';
import { ResourceForm, type ResourceFormConfig } from '@/components/platform/resource-form';
import { ResourceList } from '@/components/platform/resource-list';
import { ClampedText } from '@/components/platform/clamped-text';
import { ApiError } from '@/lib/api-client';
import { useCan } from '@/hooks/use-can';
import { useDatetime } from '@/hooks/use-datetime';
import { useAutocountCompany } from '@/hooks/use-autocount-company';
import { autocountService } from '@/services/autocount-service';
import type { AutocountCompany, AutocountEntityConfig } from '@/types/autocount';
import {
  AC_COMPANIES_PATH,
  AC_SYNC_RUN,
  acCompanyHref,
  acReviewHref,
  entityLabel,
  syncModeLabel,
} from '../../components/autocount-meta';
import { useAutocountRunsListConfig } from './use-runs-list-config';

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1 border-b border-border py-3 last:border-0 sm:grid-cols-[220px_1fr] sm:items-center sm:gap-4">
      <span className="text-sm text-muted-foreground">{label}</span>
      <div className="min-w-0 text-sm text-foreground">{children}</div>
    </div>
  );
}

interface EntityRowProps {
  entity: AutocountEntityConfig;
  companyActive: boolean;
  canRun: boolean;
  isSyncing: boolean;
  onSync: (entityType: string) => void;
}

/**
 * One configured entity + its Sync now control. The button is disabled with a
 * stated reason whenever a sync cannot succeed — never offered and then failed
 * (foolproof-UI).
 */
function EntityRow({ entity, companyActive, canRun, isSyncing, onSync }: EntityRowProps) {
  let blocked: string | null = null;
  if (!companyActive) blocked = 'This company is inactive.';
  else if (!entity.enabled) blocked = 'This entity is not enabled for sync.';

  return (
    <div className="flex flex-col gap-2 border-b border-border py-3 last:border-0 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-sm font-medium text-foreground">
          {entityLabel(entity.entityType)}
        </span>
        <span className="text-xs text-muted-foreground">
          {syncModeLabel(entity.syncMode)} · up to {entity.recordCap} records per run
        </span>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        {blocked && (
          <span className="text-xs text-muted-foreground">{blocked}</span>
        )}
        {canRun && (
          <Button
            size="sm"
            variant="outline"
            disabled={Boolean(blocked) || isSyncing}
            onClick={() => onSync(entity.entityType)}
            data-testid={`sync-${entity.entityType}`}
          >
            {isSyncing ? (
              <LoaderCircleIcon className="size-4 animate-spin" />
            ) : (
              <RefreshCw className="size-4" />
            )}
            Sync now
          </Button>
        )}
      </div>
    </div>
  );
}

export function AutocountCompanyDetailView({ companyId }: { companyId: string }) {
  const { detail, isLoading, notFound, reload } = useAutocountCompany(companyId);
  const { formatDateTime } = useDatetime();
  const { can } = useCan();
  const router = useRouter();
  const form = useForm();
  const runsConfig = useAutocountRunsListConfig(companyId);
  const [syncing, setSyncing] = useState<string | null>(null);
  const [runsKey, setRunsKey] = useState(0);

  const canRun = can(AC_SYNC_RUN);

  const onSync = useCallback(
    async (entityType: string) => {
      setSyncing(entityType);
      try {
        const job = await autocountService.syncNow(companyId, entityType);
        // Eager (dev) runs inline, so a batch can already be awaiting approval;
        // under a real worker it is still pending and the Runs tab is the place
        // to watch it.
        if (job.status === 'needs_review') {
          toast.success('Sync finished — the batch is awaiting approval.');
          router.push(acReviewHref(job.id, acCompanyHref(companyId)));
          return;
        }
        toast.success('Sync started.');
        setRunsKey((k) => k + 1);
        reload();
      } catch (error) {
        toast.error(
          error instanceof ApiError ? error.message : 'That sync could not be started.',
        );
      } finally {
        setSyncing(null);
      }
    },
    [companyId, reload, router],
  );

  const config = useMemo<ResourceFormConfig<AutocountCompany> | null>(() => {
    if (!detail) return null;
    const { company, entities } = detail;

    return {
      breadcrumb: [
        { label: 'AutoCount' },
        { label: 'Companies', href: AC_COMPANIES_PATH },
        { label: company.name },
      ],
      backHref: AC_COMPANIES_PATH,
      title: company.name,
      subtitle: company.databaseName,
      tabs: [
        {
          id: 'overview',
          label: 'Overview',
          icon: Info,
          render: () => (
            <div className="flex flex-col gap-8 py-2">
              <div className="flex flex-col">
                <DetailRow label="Company name">
                  <ClampedText text={company.companyName || '—'} lines={2} />
                </DetailRow>
                <DetailRow label="Company database">
                  <code className="text-xs">{company.databaseName}</code>
                </DetailRow>
                <DetailRow label="Status">
                  <Badge
                    variant={company.isActive ? 'success' : 'secondary'}
                    appearance="light"
                  >
                    {company.isActive ? 'Active' : 'Inactive'}
                  </Badge>
                </DetailRow>
                <DetailRow label="Integration">
                  <Link
                    href={`/settings/integrations/${company.connectionId}`}
                    className="text-primary hover:underline"
                  >
                    Open connection
                  </Link>
                </DetailRow>
                <DetailRow label="Connected">
                  {company.createdAt ? formatDateTime(company.createdAt) : '—'}
                </DetailRow>
              </div>

              <div className="flex flex-col gap-2">
                <h3 className="text-sm font-semibold text-foreground">Entities</h3>
                <div className="flex flex-col">
                  {entities.length === 0 ? (
                    <p className="py-3 text-sm text-muted-foreground">
                      No entities are configured.
                    </p>
                  ) : (
                    entities.map((entity) => (
                      <EntityRow
                        key={entity.id}
                        entity={entity}
                        companyActive={company.isActive}
                        canRun={canRun}
                        isSyncing={syncing === entity.entityType}
                        onSync={onSync}
                      />
                    ))
                  )}
                </div>
              </div>
            </div>
          ),
        },
        {
          id: 'runs',
          label: 'Runs',
          icon: History,
          render: () => (
            <div className="py-2">
              <ResourceList key={runsKey} config={runsConfig} />
            </div>
          ),
        },
      ],
      initialTabId: 'overview',
      actions: [],
      actionRows: [company],
      onReload: reload,
      // Company identity is DISCOVERED and read-only — there is nothing here an
      // operator may edit, so no Edit toggle is offered (AC-13-01).
      editable: false,
      isDirty: false,
      onSave: () => true,
      onCancel: reload,
    };
  }, [canRun, detail, formatDateTime, onSync, reload, runsConfig, runsKey, syncing]);

  if (isLoading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (notFound || !config) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Company not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={AC_COMPANIES_PATH}>Back to companies</Link>
          </Button>
        </div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>
    </Container>
  );
}
