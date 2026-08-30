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
import { toast } from 'sonner';
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
  useAutocountEtlTask,
  useAutocountSqlConnections,
  useAutocountSqlSchema,
  useEtlTaskLifecycle,
  useEtlTaskPreview,
  useSqlPreview,
} from '@/hooks/use-autocount-etl';
import { useAutocountMapping } from '@/hooks/use-autocount-mapping';
import { mappingSourceColumns } from '@/lib/autocount-etl';
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
import { QueryTab } from './query-tab';
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
  const form = useForm();
  const { can } = useCan();
  const { detail } = useAutocountCompany(companyId);
  const { task, isLoading, notFound, saveError, fieldErrors, save, apply } = useAutocountEtlTask(
    companyId,
    entityType,
  );
  const sqlConnections = useAutocountSqlConnections();
  const mapping = useAutocountMapping(companyId, entityType);
  const draft = useMappingDraft(mapping.view);
  const etlPreview = useEtlTaskPreview(companyId, entityType, apply);
  const lifecycle = useEtlTaskLifecycle(companyId, entityType, apply);
  const runsConfig = useAutocountRunsListConfig(companyId, { variant: 'task', entityType });
  const [runsKey, setRunsKey] = useState(0);

  const [config, setConfig] = useState<AutocountEtlSourceConfig | null>(null);

  // Seed the working config from the loaded/saved task. Keyed on the config
  // signature so a background reload with identical values never wipes an edit.
  const baseline = task?.sourceConfig ?? null;
  const baselineKey = useMemo(() => JSON.stringify(baseline), [baseline]);
  useEffect(() => {
    setConfig(baseline ? { ...baseline } : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baselineKey]);

  const schema = useAutocountSqlSchema(config?.connectionId ?? null);
  const preview = useSqlPreview();

  const configDirty = useMemo(() => JSON.stringify(config) !== baselineKey, [config, baselineKey]);
  const dirty = configDirty || draft.dirty;

  const onChange = useCallback((patch: Partial<AutocountEtlSourceConfig>) => {
    setConfig((prev) => (prev ? { ...prev, ...patch } : prev));
  }, []);

  const onSave = useCallback(async (): Promise<boolean> => {
    if (!config) return false;
    if (configDirty) {
      const ok = await save({ ...config, query: config.query.trim() });
      if (!ok) return false;
    }
    if (draft.dirty) {
      const problem = draft.validate();
      if (problem) {
        toast.error(problem);
        return false;
      }
      const ok = await mapping.save(draft.writeRows());
      if (!ok) return false;
    }
    toast.success('Task saved.');
    return true;
  }, [config, configDirty, draft, mapping, save]);

  const onCancel = useCallback(() => {
    setConfig(baseline ? { ...baseline } : null);
    draft.reset();
  }, [baseline, draft]);

  const onRan = useCallback(() => setRunsKey((k) => k + 1), []);

  // The Mapping tab's source picker: the saved query's columns, plus a preview
  // run this session, plus whatever the rows already reference (AC-22-09).
  const previewColumns = useMemo(
    () => (preview.state.status === 'success' ? preview.state.preview.columns.map((c) => c.name) : []),
    [preview.state],
  );
  const sourceColumns = useMemo(
    () =>
      mappingSourceColumns(
        task?.resultColumns ?? [],
        previewColumns,
        draft.rows.map((r) => r.sourcePath),
      ),
    [draft.rows, previewColumns, task?.resultColumns],
  );

  const resourceConfig = useMemo<ResourceFormConfig<AutocountEtlTask> | null>(() => {
    if (!task || !config) return null;
    const companyName = detail?.company.name;
    const label = entityLabel(entityType);
    // A query with no key columns cannot mint source_refs - shown as a
    // prerequisite warning (foolproof), never a silent later failure.
    const keysMissing = config.query.trim().length > 0 && config.keyColumns.length === 0;
    const querySaved = task.sourceConfig.query.trim().length > 0;
    const status = task.etlStatus as AutocountEtlStatus;

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
        confirm: {
          title: 'Pause this task?',
          description:
            'Scheduled runs stop until it is resumed. A run already in progress finishes.',
          confirmLabel: 'Pause',
        },
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
      title: label,
      subtitle: (
        <span className="flex flex-wrap items-center gap-2">
          {companyName && <span>{companyName}</span>}
          <Badge variant="secondary" appearance="light">
            <Database className="size-3" />
            Database
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
          label: 'Query',
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
              <QueryTab
                editing={editing}
                entityType={entityType}
                config={config}
                onChange={onChange}
                connections={sqlConnections.connections}
                connectionsLoading={sqlConnections.isLoading}
                schema={schema}
                preview={preview}
                fieldErrors={fieldErrors}
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
                  onServerTest={mapping.testFormula}
                  onSimulate={mapping.simulate}
                  entityLabel={label}
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
            <div className="py-2">
              <ActivateTab
                company={detail?.company ?? null}
                task={task}
                configDirty={dirty}
                preview={etlPreview}
                lifecycle={lifecycle}
                onRan={onRan}
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
                    <ResourceList key={runsKey} config={runsConfig} />
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
    can,
    companyId,
    config,
    detail,
    dirty,
    draft,
    entityType,
    etlPreview,
    fieldErrors,
    initialTab,
    lifecycle,
    mapping,
    onCancel,
    onChange,
    onRan,
    onSave,
    preview,
    runsConfig,
    runsKey,
    saveError,
    schema,
    sourceColumns,
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
