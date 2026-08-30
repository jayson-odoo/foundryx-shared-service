'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  CalendarClock,
  CircleCheck,
  Database,
  History,
  LoaderCircleIcon,
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
import { StatusBadge } from '@/components/platform/status-badge';
import { useAutocountCompany } from '@/hooks/use-autocount-company';
import {
  useAutocountEtlTask,
  useAutocountSqlConnections,
  useAutocountSqlSchema,
  useSqlPreview,
} from '@/hooks/use-autocount-etl';
import type {
  AutocountEtlSourceConfig,
  AutocountEtlStatus,
  AutocountEtlTask,
} from '@/types/autocount';
import {
  AC_COMPANIES_MANAGE,
  AC_COMPANIES_PATH,
  AC_ETL_STATUS_REGISTRY,
  acCompanyHref,
  entityLabel,
} from '../../../../../components/autocount-meta';
import { QueryTab } from './query-tab';

export interface TaskEditorViewProps {
  companyId: string;
  entityType: string;
}

/**
 * The Database-mode task editor (plan 22 §3): ONE surface, five tabs - Query ·
 * Mapping · Schedule · Review & Activate · Runs. Slice S1 ships the Query tab;
 * the others are present but disabled until their slices land (S2-S3), so the
 * structure is visible without offering a dead-end. Read-only by default,
 * editable under the shell's global Edit toggle, saved through its single
 * dirty-guarded save.
 */
export function TaskEditorView({ companyId, entityType }: TaskEditorViewProps) {
  const form = useForm();
  const { detail } = useAutocountCompany(companyId);
  const { task, isLoading, notFound, saveError, fieldErrors, save } = useAutocountEtlTask(
    companyId,
    entityType,
  );
  const sqlConnections = useAutocountSqlConnections();

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

  const dirty = useMemo(() => JSON.stringify(config) !== baselineKey, [config, baselineKey]);

  const onChange = useCallback((patch: Partial<AutocountEtlSourceConfig>) => {
    setConfig((prev) => (prev ? { ...prev, ...patch } : prev));
  }, []);

  const onSave = useCallback(async (): Promise<boolean> => {
    if (!config) return false;
    const ok = await save({ ...config, query: config.query.trim() });
    if (ok) toast.success('Task saved.');
    return ok;
  }, [config, save]);

  const onCancel = useCallback(() => {
    setConfig(baseline ? { ...baseline } : null);
  }, [baseline]);

  const resourceConfig = useMemo<ResourceFormConfig<AutocountEtlTask> | null>(() => {
    if (!task || !config) return null;
    const companyName = detail?.company.name;
    const label = entityLabel(entityType);
    // A query with no key columns cannot mint source_refs - shown as a
    // prerequisite warning (foolproof), never a silent later failure.
    const keysMissing = config.query.trim().length > 0 && config.keyColumns.length === 0;

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
          <StatusBadge
            status={task.etlStatus as AutocountEtlStatus}
            registry={AC_ETL_STATUS_REGISTRY}
          />
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
          disabled: true,
          render: () => null,
        },
        {
          id: 'schedule',
          label: 'Schedule',
          icon: CalendarClock,
          disabled: true,
          render: () => null,
        },
        {
          id: 'activate',
          label: 'Review & Activate',
          icon: CircleCheck,
          disabled: true,
          render: () => null,
        },
        {
          id: 'runs',
          label: 'Runs',
          icon: History,
          disabled: true,
          render: () => null,
        },
      ],
      initialTabId: 'query',
      actions: [],
      actionRows: [task],
      editable: true,
      editPermission: AC_COMPANIES_MANAGE,
      isDirty: dirty,
      onSave,
      onCancel,
    };
  }, [
    companyId,
    config,
    detail,
    dirty,
    entityType,
    fieldErrors,
    onCancel,
    onChange,
    onSave,
    preview,
    saveError,
    schema,
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
