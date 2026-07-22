'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  CircleCheck,
  History,
  Info,
  Layers,
  LoaderCircleIcon,
  TriangleAlert,
} from 'lucide-react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertIcon, AlertTitle } from '@/components/ui/alert';
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
import {
  parseSyncSummary,
  type AutocountCompany,
  type AutocountEntityConfig,
  type AutocountSinkImpl,
} from '@/types/autocount';
import {
  AC_COMPANIES_MANAGE,
  AC_COMPANIES_PATH,
  acCompanyHref,
  acReviewHref,
  entityLabel,
} from '../../components/autocount-meta';
import { DetailRow } from './detail-row';
import { EntityLookbackDialog } from './entity-lookback-dialog';
import { SinkTargetSection } from './sink-target-section';
import { useAutocountEntitiesListConfig } from './use-entities-list-config';
import { useAutocountRunsListConfig } from './use-runs-list-config';

/**
 * The outcome of the sync the operator just ran, stated where they are looking.
 *
 * A run that fetched nothing is a SUCCESSFUL no-op — the vendor genuinely had
 * no changes since the watermark — and it previously produced silence, which
 * reads as a broken button. Short empty-state status copy like this is
 * explicitly allowed by the foolproof-UI rule; procedural how-to copy is not.
 */
type SyncOutcome = { tone: 'success' | 'warning'; title: string; detail?: string };

export function AutocountCompanyDetailView({ companyId }: { companyId: string }) {
  const { detail, isLoading, notFound, reload } = useAutocountCompany(companyId);
  const { can } = useCan();
  const { formatDateTime } = useDatetime();
  const router = useRouter();
  const form = useForm();
  const runsConfig = useAutocountRunsListConfig(companyId);
  const [syncing, setSyncing] = useState<string | null>(null);
  const [runsKey, setRunsKey] = useState(0);
  const [outcome, setOutcome] = useState<SyncOutcome | null>(null);
  const [editing, setEditing] = useState<AutocountEntityConfig | null>(null);

  // Push-target working state — lifted here so the ONE Overview Resource form
  // owns its dirty flag + single save (AC-15-20), not a detached card button.
  const loadedCompany = detail?.company;
  const persistedSink: AutocountSinkImpl =
    loadedCompany?.sinkImpl === 'sorento' ? 'sorento' : 'logging';
  const persistedConnectionId = loadedCompany?.sinkConnectionId ?? null;
  const [sinkImpl, setSinkImpl] = useState<AutocountSinkImpl>('logging');
  const [sinkConnectionId, setSinkConnectionId] = useState<string | null>(null);

  // Re-seed from the persisted values whenever THEY change (after a save/reload).
  // Keyed on the persisted fields, not the whole `detail` object, so a
  // background refetch that returns identical values never wipes an in-progress
  // edit.
  useEffect(() => {
    setSinkImpl(persistedSink);
    setSinkConnectionId(persistedConnectionId);
  }, [persistedSink, persistedConnectionId]);

  const onSinkChange = useCallback((impl: AutocountSinkImpl) => {
    setSinkImpl(impl);
    // Switching back to logging clears the target — a stale connection id must
    // not linger on a no-delivery company.
    if (impl === 'logging') setSinkConnectionId(null);
  }, []);

  const sinkDirty =
    sinkImpl !== persistedSink ||
    (sinkImpl === 'sorento' && sinkConnectionId !== persistedConnectionId);

  const onSavePushTarget = useCallback(async (): Promise<boolean> => {
    // Foolproof-UI: a Sorento delivery cannot be saved without a connection.
    if (sinkImpl === 'sorento' && !sinkConnectionId) {
      toast.error('Choose a Sorento connection before saving.');
      return false;
    }
    try {
      await autocountService.updateSinkTarget(companyId, {
        sinkImpl,
        sinkConnectionId: sinkImpl === 'sorento' ? sinkConnectionId : null,
      });
      toast.success('Push target updated.');
      reload();
      return true;
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : 'That push target could not be saved.',
      );
      return false;
    }
  }, [companyId, sinkConnectionId, sinkImpl, reload]);

  const onCancelPushTarget = useCallback(() => {
    setSinkImpl(persistedSink);
    setSinkConnectionId(persistedConnectionId);
  }, [persistedSink, persistedConnectionId]);

  const onSync = useCallback(
    async (entityType: string) => {
      setSyncing(entityType);
      setOutcome(null);
      try {
        const job = await autocountService.syncNow(companyId, entityType);
        // A batch to review routes the operator to the review surface. A batch
        // with nothing in it must NOT pretend there is something to review.
        if (job.status === 'needs_review') {
          toast.success('Sync finished — the batch is awaiting approval.');
          router.push(acReviewHref(job.id, acCompanyHref(companyId)));
          return;
        }

        const summary = parseSyncSummary(job.result);
        const label = entityLabel(entityType);
        if (job.status === 'failed') {
          setOutcome({
            tone: 'warning',
            title: `${label} sync failed.`,
            detail: job.error ?? undefined,
          });
        } else if (summary && summary.failed > 0) {
          setOutcome({
            tone: 'warning',
            title: `${label}: ${summary.failed} document(s) could not be mapped.`,
            detail: 'Nothing was staged and the sync position was held.',
          });
        } else if (summary && summary.fetched === 0) {
          // The honest reading of the real case that prompted this: the window
          // was queried, the vendor returned nothing, and the watermark rightly
          // did not move.
          setOutcome({
            tone: 'success',
            title: `${label}: no changes since last sync.`,
          });
        } else if (summary) {
          setOutcome({
            tone: 'success',
            title: `${label}: ${summary.fetched} record(s) fetched.`,
          });
        } else {
          // No result yet — a real worker has the job queued.
          setOutcome({ tone: 'success', title: `${label} sync started.` });
        }
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

  const onEditLookback = useCallback((entity: AutocountEntityConfig) => {
    setEditing(entity);
  }, []);

  const onRefetch = useCallback(
    async (entity: AutocountEntityConfig) => {
      try {
        await autocountService.refetchHistory(companyId, entity.entityType);
        toast.success('History re-fetch scheduled — the next sync re-reads the window.');
        reload();
      } catch (error) {
        toast.error(
          error instanceof ApiError
            ? error.message
            : 'That history re-fetch could not be started.',
        );
      }
    },
    [companyId, reload],
  );

  const onSaveLookback = useCallback(
    async (entityType: string, days: number) => {
      try {
        await autocountService.updateEntityConfig(companyId, entityType, {
          initialLookbackDays: days,
        });
        toast.success('First-run window updated.');
        setEditing(null);
        reload();
      } catch (error) {
        toast.error(
          error instanceof ApiError
            ? error.message
            : 'That first-run window could not be saved.',
        );
      }
    },
    [companyId, reload],
  );

  const entitiesConfig = useAutocountEntitiesListConfig({
    entities: detail?.entities ?? [],
    companyActive: detail?.company.isActive ?? false,
    onSync,
    onEditLookback,
    onRefetch,
  });

  const config = useMemo<ResourceFormConfig<AutocountCompany> | null>(() => {
    if (!detail) return null;
    const { company } = detail;
    const canManage = can(AC_COMPANIES_MANAGE);

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
          render: ({ editing }) => (
            <div className="flex flex-col py-2">
              {/* Identity is DISCOVERED and read-only in either mode (AC-13-01). */}
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
              {/* Push target — read-only until the form's Edit toggle. */}
              <SinkTargetSection
                company={company}
                editing={editing && canManage}
                sinkImpl={sinkImpl}
                connectionId={sinkConnectionId}
                onSinkChange={onSinkChange}
                onConnectionChange={setSinkConnectionId}
              />
            </div>
          ),
        },
        {
          id: 'entities',
          label: 'Entities',
          icon: Layers,
          render: () => (
            <div className="flex flex-col gap-4 py-2">
              {!company.isActive && (
                <Alert variant="warning" appearance="light">
                  <AlertIcon>
                    <TriangleAlert />
                  </AlertIcon>
                  <AlertTitle>This company is inactive, so it cannot sync.</AlertTitle>
                </Alert>
              )}
              {outcome && (
                <Alert
                  variant={outcome.tone === 'success' ? 'success' : 'warning'}
                  appearance="light"
                  data-testid="sync-outcome"
                >
                  <AlertIcon>
                    {outcome.tone === 'success' ? <CircleCheck /> : <TriangleAlert />}
                  </AlertIcon>
                  <AlertTitle>{outcome.title}</AlertTitle>
                  {outcome.detail && <AlertDescription>{outcome.detail}</AlertDescription>}
                </Alert>
              )}
              {syncing && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <LoaderCircleIcon className="size-4 animate-spin" />
                  Syncing {entityLabel(syncing)}…
                </div>
              )}
              <ResourceList config={entitiesConfig} />
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
      // Company identity stays read-only, but the push target is editable — so
      // the form offers the global Edit toggle (gated on manage) and saves the
      // push target through its single, dirty-guarded save (AC-15-20).
      editable: true,
      editPermission: AC_COMPANIES_MANAGE,
      isDirty: sinkDirty,
      onSave: onSavePushTarget,
      onCancel: onCancelPushTarget,
    };
  }, [
    can,
    detail,
    entitiesConfig,
    formatDateTime,
    onCancelPushTarget,
    onSavePushTarget,
    onSinkChange,
    outcome,
    reload,
    runsConfig,
    runsKey,
    sinkConnectionId,
    sinkDirty,
    sinkImpl,
    syncing,
  ]);

  // FIRST load only. A background refetch (after a sync, after a config edit)
  // must NOT swap the page for a spinner: that unmounts `ResourceForm`, whose
  // active tab is local state, so the operator gets thrown back to Overview and
  // never sees the outcome banner they just triggered on the Entities tab.
  if (isLoading && !detail) {
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
      <EntityLookbackDialog
        entity={editing}
        onClose={() => setEditing(null)}
        onSave={onSaveLookback}
      />
    </Container>
  );
}
