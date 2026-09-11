'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  CalendarClock,
  CircleCheck,
  Database,
  History,
  LoaderCircleIcon,
  Pause,
  Play,
  SlidersHorizontal,
  TriangleAlert,
} from 'lucide-react';
import { useForm } from 'react-hook-form';
import { toast } from '@/lib/toast';
import { Container } from '@/components/common/container';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { ResourceForm, type ResourceFormConfig } from '@/components/platform/resource-form';
import type { ResourceAction } from '@/components/platform/resource-list';
import { ResourceList } from '@/components/platform/resource-list';
import { StatusBadge } from '@/components/platform/status-badge';
import { useAutocountCompany } from '@/hooks/use-autocount-company';
import { useCan } from '@/hooks/use-can';
import {
  useAutocountApiConnections,
  useAutocountEtlTask,
  useAutocountSqlConnections,
  useAutocountSqlSchema,
  useEtlTaskLifecycle,
  useEtlTaskPreview,
  useHttpPreview,
  useLineFetcher,
  useSqlPreview,
} from '@/hooks/use-autocount-etl';
import { useAutocountMapping, useAutocountMappingPresets } from '@/hooks/use-autocount-mapping';
import { HTTP_PRESETS, isDocumentEntity, mappingSourceColumns } from '@/lib/autocount-etl';
import { autocountService } from '@/services/autocount-service';
import type {
  AutocountEtlSourceConfig,
  AutocountEtlStatus,
  AutocountEtlTask,
} from '@/types/autocount';
import {
  AC_COMPANIES_MANAGE,
  AC_COMPANIES_PATH,
  AC_ETL_STATUS_REGISTRY,
  AC_SYNC_READ,
  AC_SYNC_RUN,
  acCompanyHref,
  entityLabel,
  type AcTaskTab,
} from '../../../../../components/autocount-meta';
import { useAutocountRunsListConfig } from '../../../../components/use-runs-list-config';
import { MappingEditorBody } from '../mapping/components/mapping-editor-body';
import { useMappingDraft } from '../mapping/components/use-mapping-draft';
import { ActivateTab } from './activate-tab';
import {
  SourceTab,
  type LockedApiConnection,
  type LockedConnection,
  type SourceKind,
} from './source-tab';
import { ScheduleTab } from './schedule-tab';

export interface TaskEditorViewProps {
  companyId: string;
  entityType: string;
  /** Tab to open (the entities list deep-links Mapping; default Query). */
  initialTab?: AcTaskTab;
}

/**
 * The Database-mode task editor (plan 22 §3): ONE surface, five tabs - Query ·
 * Mapping · Schedule · Review & Activate · Runs. Read-only by default, editable
 * under the shell's global Edit toggle; the Query config AND the Mapping rows
 * save through its single dirty-guarded save. Schedule stays disabled until S3;
 * Mapping and Review & Activate open once a query is saved (before that they
 * would be dead-ends), Runs is always there (empty until the task runs).
 */
export function TaskEditorView({ companyId, entityType, initialTab = 'query' }: TaskEditorViewProps) {
  const form = useForm({ mode: 'onTouched' });
  const { can } = useCan();
  const { detail } = useAutocountCompany(companyId);
  const { task, isLoading, notFound, saveError, fieldErrors, save, apply, reload } =
    useAutocountEtlTask(companyId, entityType);
  const sqlConnections = useAutocountSqlConnections();
  const apiConnections = useAutocountApiConnections();
  const httpPreview = useHttpPreview();
  const mapping = useAutocountMapping(companyId, entityType);
  const draft = useMappingDraft(mapping.view);
  const { presets } = useAutocountMappingPresets(companyId, entityType);
  const { fetchLines } = useLineFetcher();
  const etlPreview = useEtlTaskPreview(companyId, entityType, apply);
  const lifecycle = useEtlTaskLifecycle(companyId, entityType, apply);
  const runsConfig = useAutocountRunsListConfig(companyId, { variant: 'task', entityType });
  const [runsKey, setRunsKey] = useState(0);

  const [config, setConfig] = useState<AutocountEtlSourceConfig | null>(null);
  // The task's Source (sprint-5/08, D13) - API | Database, the ONE place the
  // choice is made. Lifted here (not local to `SourceTab`) so the shell's
  // dirty guard and the derived-impl save both see it.
  const [sourceKind, setSourceKind] = useState<SourceKind>('db');

  // A DB company's task is locked to the company connection (AC-01-19) - the
  // Database branch shows it read-only (`name · database`) instead of the picker.
  const company = detail?.company ?? null;
  const lockedConnection = useMemo<LockedConnection | null>(() => {
    if (!company || company.sourceKind !== 'db') return null;
    const conn = sqlConnections.connections.find((c) => c.id === company.connectionId);
    return {
      id: company.connectionId,
      label: conn ? `${conn.name} · ${conn.database}` : company.databaseName,
    };
  }, [company, sqlConnections.connections]);

  // An http/api company's API branch is locked to the company's OWN
  // connection (sprint-5/08, AC-08-19) - only a `db` company keeps the free
  // cross-tenant picker (AC-08-13: an HTTP task on a DB company may
  // reference ANY open connection of the tenant).
  const lockedApiConnection = useMemo<LockedApiConnection | null>(() => {
    if (!company || (company.sourceKind !== 'http' && company.sourceKind !== 'api')) return null;
    const conn = apiConnections.connections.find((c) => c.id === company.connectionId);
    return {
      id: company.connectionId,
      label: conn?.name ?? company.databaseName ?? company.name,
      auth: conn?.auth ?? (company.sourceKind === 'http' ? 'none' : 'basic'),
    };
  }, [apiConnections.connections, company]);

  // The Source toggle's default per company kind (AC-08-18): `db` -> Database,
  // `http`/`api` -> API.
  const defaultSourceKind: SourceKind = company?.sourceKind === 'db' ? 'db' : 'api';

  // The saved config is the dirty BASELINE. A never-configured entity's draft
  // carries `connectionId: null`, so the locked connection (whichever branch
  // applies) is seeded here (not patched after mount): an untouched editor
  // stays clean (no "Discard changes?" on Edit -> Cancel) and the first save
  // carries the company connection without the operator having to notice.
  // The task's saved Source: an `autocount_http` task reads 'api'; a
  // `sql_db` task with a saved query reads 'db' regardless of the company's
  // own default (an already-configured task is never silently re-toggled);
  // a never-configured task falls through to the company default (AC-08-18).
  const baselineSourceKind = useMemo<SourceKind>(() => {
    if (!task) return defaultSourceKind;
    const impl = task.sourceImpl ?? 'sql_db';
    if (impl === 'autocount_http') return 'api';
    if (task.sourceConfig.query.trim()) return 'db';
    return defaultSourceKind;
  }, [defaultSourceKind, task]);

  const baseline = useMemo<AutocountEtlSourceConfig | null>(() => {
    const saved = task?.sourceConfig ?? null;
    if (!saved) return saved;
    const lockId = lockedConnection?.id ?? lockedApiConnection?.id;
    if (!lockId) return saved;
    return { ...saved, connectionId: saved.connectionId ?? lockId };
  }, [lockedApiConnection, lockedConnection, task?.sourceConfig]);

  // Seed the working config + Source toggle from the baseline. Keyed on the
  // config signature so a background reload with identical values never
  // wipes an edit. Foolproof-UI (AC-08-16): a never-configured task that
  // opens straight onto API (the company's own default, AC-08-18) is
  // pre-filled from its HTTP preset HERE, onto the WORKING config only -
  // never baked into `baseline` itself (unlike the connection lock above).
  // The preset is a genuinely unsaved change: nothing has reached the
  // backend/mock yet, so `configDirty` must read true (a real Save is
  // needed) rather than looking already-clean against a baseline that
  // quietly carried the same values.
  const baselineKey = useMemo(
    () => JSON.stringify({ baseline, baselineSourceKind }),
    [baseline, baselineSourceKind],
  );
  useEffect(() => {
    let seeded = baseline ? { ...baseline } : null;
    if (seeded && baselineSourceKind === 'api' && !seeded.path?.trim() && !seeded.query.trim()) {
      const preset = HTTP_PRESETS[entityType];
      if (preset) {
        seeded = {
          ...seeded,
          path: preset.path,
          keyFields: preset.keyFields,
          watermarkField: preset.watermarkField,
          // Mirrors onto the SQL field name too - ScheduleTab's incremental-
          // floor check reads `watermarkColumn` unconditionally (AC-08-19).
          watermarkColumn: preset.watermarkField,
          comparedFields: preset.comparedFields,
          distinctOf: preset.distinctOf,
        };
      }
    }
    setConfig(seeded);
    setSourceKind(baselineSourceKind);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baselineKey]);

  const schema = useAutocountSqlSchema(config?.connectionId ?? null);
  const preview = useSqlPreview();
  // A SEPARATE preview instance for a document's line query (plan 22 S5) -
  // its own loading/error/success state, independent of the header preview.
  const linePreview = useSqlPreview();

  const configDirty = useMemo(() => JSON.stringify(config) !== JSON.stringify(baseline), [config, baseline]);
  const sourceKindDirty = sourceKind !== baselineSourceKind;
  const dirty = configDirty || sourceKindDirty || draft.dirty;

  const onChange = useCallback((patch: Partial<AutocountEtlSourceConfig>) => {
    setConfig((prev) => (prev ? { ...prev, ...patch } : prev));
  }, []);

  const onSourceKindChange = useCallback(
    (kind: SourceKind) => {
      setSourceKind(kind);
      preview.reset();
      linePreview.reset();
      httpPreview.reset();
      setConfig((prev) => {
        if (!prev) return prev;
        if (kind === 'db') {
          const id =
            lockedConnection?.id ??
            (sqlConnections.connections.some((c) => c.id === prev.connectionId) ? prev.connectionId : null);
          return { ...prev, connectionId: id };
        }
        const id =
          lockedApiConnection?.id ??
          (apiConnections.connections.some((c) => c.id === prev.connectionId) ? prev.connectionId : null);
        // Foolproof-UI (AC-08-16): a never-configured HTTP-capable entity's
        // Source tab opens pre-filled from its preset the FIRST time API is
        // picked - never overwriting an operator's own already-typed path.
        const preset = !prev.path?.trim() ? HTTP_PRESETS[entityType] : null;
        return {
          ...prev,
          connectionId: id,
          ...(preset
            ? {
                path: preset.path,
                keyFields: preset.keyFields,
                watermarkField: preset.watermarkField,
                watermarkColumn: preset.watermarkField,
                comparedFields: preset.comparedFields,
                distinctOf: preset.distinctOf,
              }
            : {}),
        };
      });
    },
    [apiConnections.connections, entityType, httpPreview, linePreview, lockedApiConnection, lockedConnection, preview, sqlConnections.connections],
  );

  // The derived source impl (sprint-5/08 D13/plan §2.8): Database -> `sql_db`;
  // API + a no-auth connection -> `autocount_http`; API + a basic-auth
  // connection -> `autocount_read` (the OLD vendor-login entity path - no
  // task at all, saved through `updateEntityConfig` instead of `save()`).
  const derivedApiAuth =
    sourceKind === 'api'
      ? (lockedApiConnection?.auth ??
        apiConnections.connections.find((c) => c.id === config?.connectionId)?.auth ??
        null)
      : null;
  const derivedImpl: 'sql_db' | 'autocount_http' | 'autocount_read' =
    sourceKind === 'db' ? 'sql_db' : derivedApiAuth === 'none' ? 'autocount_http' : 'autocount_read';

  const onSave = useCallback(async (): Promise<boolean> => {
    if (!config) return false;
    if (derivedImpl === 'autocount_read') {
      // The vendor-login path (sprint-5/08 D13): no task, no mapping draft to
      // fold in - a bare entity-config PATCH, mirroring the old
      // `EntitySourceDialog`'s save.
      try {
        await autocountService.updateEntityConfig(companyId, entityType, {
          sourceImpl: 'autocount_read',
        });
      } catch (error) {
        toast.error(error instanceof Error ? error.message : 'That source could not be saved.');
        return false;
      }
      toast.success('Task saved.');
      reload();
      return true;
    }
    if (configDirty || sourceKindDirty) {
      const ok = await save({ ...config, query: config.query.trim() }, derivedImpl);
      if (!ok) return false;
      // A document entity's FIRST clean config save seeds its field mapping
      // server-side (`seed_document_mapping`) - the Mapping tab's own hook
      // mounted before that seed existed (its 404 latched `notFound=true`),
      // so it never sees the new rows without an explicit reload.
      //
      // SF1 (final reviewer pass) - but ONLY when the mapping draft is
      // CLEAN. `mapping.save()` below already sets the fresh view itself
      // (`useAutocountMapping.save` calls `setView(next)`) - reloading here
      // TOO when the draft is also dirty fires a second, redundant, RACY
      // refetch that can resolve in either order against the save's own
      // state update.
      if (!draft.dirty) {
        mapping.reload();
      }
    }
    if (draft.dirty) {
      const problem = draft.validate();
      if (problem) {
        toast.error(problem);
        return false;
      }
      const { rows, lineRows } = draft.writeRowsForSave();
      const ok = await mapping.save(rows, lineRows);
      if (!ok) return false;
    }
    toast.success('Task saved.');
    return true;
  }, [companyId, config, configDirty, derivedImpl, draft, entityType, mapping, reload, save, sourceKindDirty]);

  const onCancel = useCallback(() => {
    setConfig(baseline ? { ...baseline } : null);
    setSourceKind(baselineSourceKind);
    draft.reset();
  }, [baseline, baselineSourceKind, draft]);

  const onRan = useCallback(() => setRunsKey((k) => k + 1), []);

  // The Mapping tab's source picker: the saved query's columns, plus a preview
  // run this session, plus whatever the rows already reference (AC-22-09).
  const previewColumns = useMemo(
    () => (preview.state.status === 'success' ? preview.state.preview.columns.map((c) => c.name) : []),
    [preview.state],
  );
  // Source-column name -> reported type, from the SAME preview - drives the
  // Mapping tab's `status` seed-formula pre-fill (S5 review SHOULD-FIX 4c).
  // Empty until a preview has been run this session; a missing type simply
  // skips the seed (never guessed).
  const columnTypes = useMemo(
    () =>
      preview.state.status === 'success'
        ? Object.fromEntries(preview.state.preview.columns.map((c) => [c.name, c.type]))
        : {},
    [preview.state],
  );
  const sourceColumns = useMemo(
    () =>
      mappingSourceColumns(
        task?.resultColumns ?? [],
        previewColumns,
        draft.header.rows.map((r) => r.sourcePath),
      ),
    [draft.header.rows, previewColumns, task?.resultColumns],
  );

  // The Mapping tab's LINE source picker (sprint-5/02, AC-02-02/06) - the
  // task's persisted `line_result_columns` (via the mapping view's
  // `lineAcFields`), plus this session's line preview, plus whatever the
  // line rows already reference.
  const linePreviewColumns = useMemo(
    () => (linePreview.state.status === 'success' ? linePreview.state.preview.columns.map((c) => c.name) : []),
    [linePreview.state],
  );
  const lineColumnTypes = useMemo(
    () =>
      linePreview.state.status === 'success'
        ? Object.fromEntries(linePreview.state.preview.columns.map((c) => [c.name, c.type]))
        : {},
    [linePreview.state],
  );
  const lineSourceColumns = useMemo(
    () =>
      mappingSourceColumns(
        mapping.view?.lineAcFields ?? [],
        linePreviewColumns,
        draft.line?.rows.map((r) => r.sourcePath) ?? [],
      ),
    [draft.line, linePreviewColumns, mapping.view?.lineAcFields],
  );

  // The Simulate dialog's document mode (AC-02-22) - the header query's last
  // Test-query preview rows + a per-header line fetch bound to `:doc_key`.
  const headerPreviewRows = useMemo(
    () => (preview.state.status === 'success' ? preview.state.preview.rows : []),
    [preview.state],
  );
  const onFetchLines = useCallback(
    async (docKey: string) => {
      if (!config?.connectionId || !config.lineQuery) return [];
      const result = await fetchLines(config.connectionId, config.lineQuery, docKey);
      return result.rows;
    },
    [config?.connectionId, config?.lineQuery, fetchLines],
  );
  const onUsePreset = useCallback(
    (preset: import('@/types/autocount').AutocountMappingPreset) => {
      onChange({
        query: preset.headerQuery,
        lineQuery: preset.lineQuery,
        keyColumns: preset.keyColumns,
        watermarkColumn: preset.watermarkColumn,
        docDateColumn: preset.docDateColumn,
        fromDate: preset.fromDate,
        filterFormula: preset.filterFormula,
      });
    },
    [onChange],
  );

  const resourceConfig = useMemo<ResourceFormConfig<AutocountEtlTask> | null>(() => {
    if (!task || !config) return null;
    const companyName = detail?.company.name;
    const label = entityLabel(entityType);
    // A query/endpoint with no key columns cannot mint source_refs - shown
    // as a prerequisite warning (foolproof), never a silent later failure.
    const keysMissing =
      sourceKind === 'db'
        ? config.query.trim().length > 0 && config.keyColumns.length === 0
        : Boolean(config.path?.trim()) && (config.keyFields?.length ?? 0) === 0;
    const querySaved =
      task.sourceConfig.query.trim().length > 0 || Boolean(task.sourceConfig.path?.trim());
    const status = task.etlStatus as AutocountEtlStatus;
    // AC-08-28 - a task demoted back to draft by a source change (impl,
    // connection, or path) keeps its `activatedAt` stamp, so a draft task
    // that HAS one was active before this save - never a fresh, never-run task.
    const revertedBySourceChange = status === 'draft' && Boolean(task.activatedAt);
    // AC-08-18: derived from the WORKING Source-tab state (`derivedImpl`),
    // never the saved task alone - a never-configured task's `sourceImpl` is
    // absent, so reading `task.sourceImpl` straight would badge "Database"
    // even on an `http` company's freshly-opened, never-saved editor.
    const sourceBadgeLabel = derivedImpl === 'autocount_http' ? 'Open API' : 'Database';

    // The lifecycle in the form "…" so it is reachable from every tab; the
    // Review & Activate tab carries the same buttons beside the preview.
    const actions: ResourceAction<AutocountEtlTask>[] = [
      {
        id: 'run-now',
        label: 'Run now',
        icon: Play,
        surfaces: { form: true },
        permission: AC_SYNC_RUN,
        isVisible: () => status === 'active',
        isDisabled: () => lifecycle.busy !== null,
        run: async () => {
          const runId = await lifecycle.runNow();
          if (runId) {
            toast.success('Run finished.');
            onRan();
          }
        },
      },
      {
        id: 'pause',
        label: 'Pause',
        icon: Pause,
        surfaces: { form: true },
        permission: AC_COMPANIES_MANAGE,
        isVisible: () => status === 'active',
        isDisabled: () => lifecycle.busy !== null,
        // Fix round 1 item 15: Pause is reversible with a single click
        // (Resume, right below, has never had a confirm) - a run already in
        // progress finishes regardless, so there's nothing destructive to
        // gate. Genuinely not a delete/detach action, so it drops `confirm`
        // entirely rather than moving to the grace-window engine.
        run: async () => {
          if (await lifecycle.pause()) toast.success('Task paused.');
        },
      },
      {
        id: 'resume',
        label: 'Resume',
        icon: Play,
        surfaces: { form: true },
        permission: AC_COMPANIES_MANAGE,
        isVisible: () => status === 'paused',
        isDisabled: () => lifecycle.busy !== null,
        run: async () => {
          if (await lifecycle.resume()) toast.success('Task resumed.');
        },
      },
    ];

    return {
      breadcrumb: [
        { label: 'AutoCount' },
        { label: 'Companies', href: AC_COMPANIES_PATH },
        ...(companyName ? [{ label: companyName, href: acCompanyHref(companyId) }] : []),
        { label },
      ],
      backHref: acCompanyHref(companyId),
      // This route lives under the company detail page (not its own list),
      // so the sidebar-derived noun would resolve to "company" (AC-DLA-35
      // fix round 1) - override with the actual entity being saved.
      entityNoun: 'task',
      title: label,
      subtitle: (
        <span className="flex flex-wrap items-center gap-2">
          {companyName && <span>{companyName}</span>}
          <Badge variant="secondary" appearance="light">
            <Database className="size-3" />
            {sourceBadgeLabel}
          </Badge>
          <StatusBadge status={status} registry={AC_ETL_STATUS_REGISTRY} />
          {task.lastRunError && (
            <Badge variant="destructive" appearance="light" size="sm" data-testid="task-header-error">
              Last run failed
            </Badge>
          )}
        </span>
      ),
      tabs: [
        {
          id: 'query',
          label: 'Source',
          icon: Database,
          render: ({ editing }) => (
            <div className="flex flex-col gap-4 py-2">
              {saveError && (
                <Alert variant="destructive" appearance="light" data-testid="task-save-error">
                  <AlertIcon>
                    <TriangleAlert />
                  </AlertIcon>
                  <AlertTitle>{saveError}</AlertTitle>
                </Alert>
              )}
              {keysMissing && (
                <Alert variant="warning" appearance="light" data-testid="task-keys-missing">
                  <AlertIcon>
                    <TriangleAlert />
                  </AlertIcon>
                  <AlertTitle>No key columns picked yet.</AlertTitle>
                </Alert>
              )}
              <SourceTab
                editing={editing}
                entityType={entityType}
                sourceKind={sourceKind}
                onSourceKindChange={onSourceKindChange}
                config={config}
                onChange={onChange}
                connections={sqlConnections.connections}
                connectionsLoading={sqlConnections.isLoading}
                lockedConnection={lockedConnection}
                schema={schema}
                preview={preview}
                linePreview={linePreview}
                fieldErrors={fieldErrors}
                presets={presets}
                onUsePreset={onUsePreset}
                onServerTest={mapping.testFormula}
                apiConnections={apiConnections.connections}
                apiConnectionsLoading={apiConnections.isLoading}
                lockedApiConnection={lockedApiConnection}
                httpPreview={httpPreview}
                companyId={companyId}
              />
            </div>
          ),
        },
        {
          id: 'mapping',
          label: 'Mapping',
          icon: SlidersHorizontal,
          disabled: !querySaved,
          render: ({ editing }) => (
            <div className="py-2">
              {mapping.isLoading && !mapping.view ? (
                <div className="flex items-center justify-center py-12 text-muted-foreground">
                  <LoaderCircleIcon className="size-5 animate-spin" />
                </div>
              ) : mapping.notFound || !mapping.view ? (
                <Alert variant="destructive" appearance="light" data-testid="task-mapping-error">
                  <AlertIcon>
                    <TriangleAlert />
                  </AlertIcon>
                  <AlertTitle>The mapping could not be loaded.</AlertTitle>
                </Alert>
              ) : (
                <MappingEditorBody
                  editing={editing}
                  draft={draft}
                  saveError={mapping.saveError}
                  sourceMode="column"
                  sourceOptions={sourceColumns}
                  lineSourceOptions={lineSourceColumns}
                  onServerTest={mapping.testFormula}
                  onSimulate={mapping.simulate}
                  entityLabel={label}
                  entityType={entityType}
                  columnTypes={columnTypes}
                  lineColumnTypes={lineColumnTypes}
                  headerPreviewRows={headerPreviewRows}
                  headerKeyColumns={config.keyColumns}
                  onFetchLines={isDocumentEntity(entityType) ? onFetchLines : undefined}
                />
              )}
            </div>
          ),
        },
        {
          id: 'schedule',
          label: 'Schedule',
          icon: CalendarClock,
          disabled: !querySaved,
          render: ({ editing }) => (
            <div className="py-2">
              <ScheduleTab
                editing={editing}
                entityType={entityType}
                config={config}
                onChange={onChange}
                task={task}
                fieldErrors={fieldErrors}
              />
            </div>
          ),
        },
        {
          id: 'activate',
          label: 'Review & Activate',
          icon: CircleCheck,
          disabled: !querySaved,
          render: () => (
            <div className="flex flex-col gap-4 py-2">
              {revertedBySourceChange && (
                <Alert variant="warning" appearance="light" data-testid="task-source-reverted">
                  <AlertIcon>
                    <TriangleAlert />
                  </AlertIcon>
                  <AlertTitle>
                    Changing the source returned this task to draft - test and re-activate to
                    resume syncing.
                  </AlertTitle>
                </Alert>
              )}
              <ActivateTab
                company={detail?.company ?? null}
                task={task}
                configDirty={dirty}
                preview={etlPreview}
                lifecycle={lifecycle}
                onRan={onRan}
                entities={detail?.entities ?? []}
                reloadTask={reload}
              />
            </div>
          ),
        },
        // Backend split (S2 review SHOULD-FIX 7): reading run history is
        // gated `autocount.sync.read` on the server (GET .../etl-task/runs)
        // - a DIFFERENT resource than the page's own `companies.manage`, so
        // it is omitted entirely rather than shown disabled (foolproof-UI:
        // only offer valid options).
        ...(can(AC_SYNC_READ)
          ? [
              {
                id: 'runs' as const,
                label: 'Runs',
                icon: History,
                render: () => (
                  <div className="py-2">
                    <ResourceList key={runsKey} config={runsConfig} hideHeader />
                  </div>
                ),
              },
            ]
          : []),
      ],
      initialTabId: initialTab,
      actions,
      actionRows: [task],
      editable: true,
      editPermission: AC_COMPANIES_MANAGE,
      isDirty: dirty,
      onSave,
      onCancel,
    };
  }, [
    apiConnections.connections,
    apiConnections.isLoading,
    can,
    columnTypes,
    companyId,
    config,
    derivedImpl,
    detail,
    dirty,
    draft,
    entityType,
    etlPreview,
    fieldErrors,
    headerPreviewRows,
    httpPreview,
    initialTab,
    lifecycle,
    lineColumnTypes,
    linePreview,
    lineSourceColumns,
    lockedApiConnection,
    lockedConnection,
    mapping,
    onCancel,
    onChange,
    onFetchLines,
    onRan,
    onSave,
    onSourceKindChange,
    onUsePreset,
    presets,
    preview,
    reload,
    runsConfig,
    runsKey,
    saveError,
    schema,
    sourceColumns,
    sourceKind,
    sqlConnections.connections,
    sqlConnections.isLoading,
    task,
  ]);

  if (isLoading && !task) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (notFound || !resourceConfig) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Task not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={acCompanyHref(companyId)}>Back to company</Link>
          </Button>
        </div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={resourceConfig} />
      </Form>
    </Container>
  );
}
