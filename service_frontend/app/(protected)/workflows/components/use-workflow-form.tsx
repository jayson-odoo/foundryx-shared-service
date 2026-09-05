'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  FileText,
  History,
  ScrollText,
  Workflow as WorkflowIcon,
} from 'lucide-react';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { toast } from '@/lib/toast';
import type {
  Workflow,
  WorkflowDefinition,
  WorkflowManualInput,
  WorkflowMetadata,
  WorkflowOmnichannelTestSource,
  WorkflowRunNode,
  WorkflowRunRequest,
} from '@/types/workflows';
import {
  createBlankDefinition,
  topoOrder,
  validateDefinition,
} from '@/lib/workflow-doc';
import { workflowPublishIssue } from '@/lib/workflow-validation';
import { workflowMetadataService } from '@/services/workflow-metadata-service';
import { workflowService } from '@/services/workflow-service';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { ListQuery } from '@/types/resource';
import type {
  TemplateOption,
  WorkflowDebugBundle,
} from '@/components/platform/workflow-canvas';
import { WorkflowRuns } from '@/components/platform/workflow-runs';
import { workflowFormHref, workflowPath, WORKFLOWS_PATH } from './paths';
import { RunDialog } from './run-dialog';
import { useWorkflowActions } from './use-workflow-actions';
import { WorkflowEditorTab } from './workflow-editor-tab';
import { WorkflowSettingsFields } from './workflow-settings-fields';
import { WorkflowVersionsTab } from './workflow-versions-tab';

export interface WorkflowFormValues {
  name: string;
  description: string;
}

export interface UseWorkflowFormResult {
  config: ResourceFormConfig<Workflow> | null;
  form: UseFormReturn<WorkflowFormValues>;
  isLoading: boolean;
  notFound: boolean;
}

/** A synthetic Workflow shell so the Editor toolbar renders in create mode. */
function blankWorkflow(): Workflow {
  return {
    id: '',
    name: '',
    description: '',
    isActive: false,
    isTrashed: false,
    triggerType: '',
    triggerLabel: '-',
    currentVersionNumber: null,
    hasUnpublishedChanges: false,
    lastRunAt: null,
    lastRunStatus: null,
    draftDefinition: createBlankDefinition(),
    currentVersionId: null,
    currentVersion: null,
    createdByName: '',
    createdAt: '',
    updatedAt: '',
  };
}

/**
 * Stale start-nodes + every descendant reachable along the TAKEN path the run
 * took (D6). At an IF node we follow only the branch the cached run executed
 * (`outputJson.passed`), mirroring the backend's branch-aware re-run - so an
 * edit never marks the untaken branch stale.
 */
function takenDescendants(
  startIds: string[],
  doc: WorkflowDefinition,
  cache: Record<string, WorkflowRunNode>,
): Set<string> {
  const outEdges = new Map<string, { port: string; target: string }[]>();
  for (const e of doc.edges) {
    const list = outEdges.get(e.source) ?? [];
    list.push({ port: e.sourcePort ?? 'out', target: e.target });
    outEdges.set(e.source, list);
  }
  const kindById = new Map(doc.nodes.map((n) => [n.id, n.kind]));
  const result = new Set<string>(startIds);
  const queue = [...startIds];
  while (queue.length) {
    const id = queue.shift() as string;
    const isIf = kindById.get(id) === 'if';
    const takenPort = isIf
      ? (cache[id]?.outputJson as { passed?: boolean } | undefined)?.passed
        ? 'true'
        : 'false'
      : null;
    for (const { port, target } of outEdges.get(id) ?? []) {
      if (isIf && port !== takenPort) continue;
      if (!result.has(target)) {
        result.add(target);
        queue.push(target);
      }
    }
  }
  return result;
}

/**
 * `workflowId === undefined` = create mode (/workflows/new).
 * `debugRunId` (?debug=) = load that run's graph + data into the editor (Logs →
 * Debug in editor). The fix persists as the draft for future runs (D16).
 */
export function useWorkflowForm(
  workflowId: string | undefined,
  initialEditing: boolean,
  canManage: boolean,
  debugRunId?: string,
  canCode = true,
): UseWorkflowFormResult {
  const router = useRouter();
  const actions = useWorkflowActions();
  const isNew = workflowId === undefined;

  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [doc, setDoc] = useState<WorkflowDefinition>(() =>
    createBlankDefinition(),
  );
  const docRef = useRef(doc);
  const runPreparationRef = useRef(false);
  const [docDirty, setDocDirty] = useState(false);
  const [templateOptions, setTemplateOptions] = useState<TemplateOption[]>([]);
  const [metadata, setMetadata] = useState<WorkflowMetadata>({ entities: [] });
  const [testSources, setTestSources] = useState<
    WorkflowOmnichannelTestSource[]
  >([]);
  const [testOptionsLoading, setTestOptionsLoading] = useState(false);
  const [testOptionsError, setTestOptionsError] = useState(false);
  const [isLoading, setIsLoading] = useState(!isNew);
  const [notFound, setNotFound] = useState(false);
  const [busy, setBusy] = useState(false);
  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [runsReloadToken, setRunsReloadToken] = useState(0);

  // ---- debug session (Logs → Debug in editor) ----
  const [debugCache, setDebugCache] = useState<Record<
    string,
    WorkflowRunNode
  > | null>(null);
  const [debugStale, setDebugStale] = useState<Set<string>>(new Set());
  const [debugBusy, setDebugBusy] = useState(false);

  const form = useForm<WorkflowFormValues>({
    defaultValues: { name: '', description: '' },
  });

  useEffect(() => {
    workflowService
      .listTemplateOptions()
      .then(setTemplateOptions)
      .catch(() => undefined);
    workflowMetadataService
      .getMetadata()
      .then(setMetadata)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (isNew) return;
    let cancelled = false;
    setIsLoading(true);
    (async () => {
      const loaded = await workflowService.get(workflowId);
      if (cancelled) return;
      if (!loaded) {
        setNotFound(true);
        setIsLoading(false);
        return;
      }
      setWorkflow(loaded);
      form.reset({ name: loaded.name, description: loaded.description });

      // Always edit the live DRAFT - debug never replaces it (n8n behavior).
      docRef.current = loaded.draftDefinition;
      setDoc(loaded.draftDefinition);

      // Debug handoff: OVERLAY the run's data onto the matching draft nodes
      // (by id); unrelated draft nodes stay as they are, no data.
      if (debugRunId) {
        const run = await workflowService.getRun(debugRunId);
        if (cancelled) return;
        if (run) {
          setDebugCache(
            Object.fromEntries(run.nodes.map((n) => [n.nodeId, n])),
          );
          setDebugStale(new Set());
        } else {
          toast.error('That run no longer exists.');
          setDebugCache(null);
        }
      } else {
        setDebugCache(null);
      }
      setIsLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [workflowId, isNew, debugRunId, form]);

  const handleDocChange = useCallback(
    (next: WorkflowDefinition) => {
      // While debugging, an edit marks that node stale AND propagates staleness
      // to its taken-branch descendants (D6 - a fresh upstream output
      // invalidates everything downstream of it on the path the run took).
      if (debugCache) {
        const prev = docRef.current;
        const prevById = new Map(prev.nodes.map((n) => [n.id, n]));
        const changed = next.nodes.filter(
          (n) =>
            JSON.stringify(prevById.get(n.id)?.config) !==
            JSON.stringify(n.config),
        );
        if (changed.length) {
          const restale = takenDescendants(
            changed.map((n) => n.id),
            next,
            debugCache,
          );
          setDebugStale(
            (s) => new Set([...Array.from(s), ...Array.from(restale)]),
          );
        }
      }
      docRef.current = next;
      setDoc(next);
      setDocDirty(true);
    },
    [debugCache],
  );

  const refresh = useCallback(
    async (id: string) => {
      const fresh = await workflowService.get(id);
      if (fresh) {
        setWorkflow(fresh);
        docRef.current = fresh.draftDefinition;
        setDoc(fresh.draftDefinition);
        form.reset({ name: fresh.name, description: fresh.description });
        setDocDirty(false);
      }
    },
    [form],
  );

  const onSave = useCallback(async (): Promise<boolean> => {
    const values = form.getValues();
    if (!values.name.trim()) {
      toast.error('Name is required.');
      return false;
    }
    const definitionIssue = validateDefinition(docRef.current, metadata).find(
      (issue) => issue.level === 'error',
    );
    if (definitionIssue) {
      toast.error(definitionIssue.message);
      return false;
    }
    const input = {
      name: values.name.trim(),
      description: values.description.trim(),
      draftDefinition: docRef.current,
    };
    try {
      if (isNew) {
        const created = await workflowService.create(input);
        toast.success(`Workflow "${created.name}" created.`);
        router.replace(workflowPath(created.id));
      } else {
        const updated = await workflowService.update(workflowId, input);
        setWorkflow(updated);
        form.reset({ name: updated.name, description: updated.description });
        toast.success('Workflow saved.');
      }
      // Do not clear a newer edit made while the save was in flight.
      if (docRef.current === input.draftDefinition) setDocDirty(false);
      return true;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Save failed.');
      return false;
    }
  }, [form, isNew, metadata, router, workflowId]);

  const onCancel = useCallback(() => {
    if (isNew) {
      router.push(WORKFLOWS_PATH);
      return;
    }
    if (workflow) {
      docRef.current = workflow.draftDefinition;
      setDoc(workflow.draftDefinition);
      form.reset({ name: workflow.name, description: workflow.description });
    }
    setDocDirty(false);
  }, [form, isNew, router, workflow]);

  const onPublish = useCallback(async () => {
    if (!workflowId) return;
    const definitionIssue = validateDefinition(docRef.current, metadata).find(
      (issue) => issue.level === 'error',
    );
    if (definitionIssue) {
      toast.error(definitionIssue.message);
      return;
    }
    const publishIssue = workflowPublishIssue(
      { ...(workflow ?? blankWorkflow()), draftDefinition: docRef.current },
      metadata,
      canCode,
    );
    if (publishIssue) {
      toast.error(publishIssue);
      return;
    }
    setBusy(true);
    try {
      if (docDirty) {
        const ok = await onSave();
        if (!ok) return;
      }
      await workflowService.publish(workflowId);
      await refresh(workflowId);
      toast.success('Published - the trigger can now fire this workflow.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Publish failed.');
    } finally {
      setBusy(false);
    }
  }, [canCode, workflowId, docDirty, metadata, onSave, refresh, workflow]);

  const onUnpublish = useCallback(async () => {
    if (!workflowId) return;
    setBusy(true);
    try {
      await workflowService.unpublish(workflowId);
      await refresh(workflowId);
      toast.success('Unpublished - the trigger will no longer fire it.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Unpublish failed.');
    } finally {
      setBusy(false);
    }
  }, [workflowId, refresh]);

  const onSetActive = useCallback(
    async (active: boolean) => {
      if (!workflowId) return;
      setBusy(true);
      try {
        await workflowService.setActive(workflowId, active);
        await refresh(workflowId);
        toast.success(active ? 'Workflow activated.' : 'Workflow deactivated.');
      } catch (e) {
        toast.error(e instanceof Error ? e.message : 'Update failed.');
      } finally {
        setBusy(false);
      }
    },
    [workflowId, refresh],
  );

  const trigger = useMemo(
    () => doc.nodes.find((node) => node.kind === 'trigger'),
    [doc],
  );

  const triggerInputs = useMemo<WorkflowManualInput[]>(() => {
    const inputs = trigger?.config.inputs;
    return Array.isArray(inputs) ? (inputs as WorkflowManualInput[]) : [];
  }, [trigger]);

  const runSideEffects = useMemo(
    () => ({
      callsAi: doc.nodes.some((node) => node.type === 'ai_agent.run'),
      sendsMessage: doc.nodes.some(
        (node) => node.type === 'omnichannel.send_message',
      ),
      mutatesRedis: doc.nodes.some((node) => {
        if (node.type !== 'redis.command') return false;
        const operation = node.config.operation;
        return (
          typeof operation === 'string' &&
          ['set', 'delete', 'increment', 'list_push', 'list_pop'].includes(
            operation,
          )
        );
      }),
      runsCode: doc.nodes.some((node) => node.type === 'code.run'),
    }),
    [doc],
  );

  const doRun = useCallback(
    async (request: WorkflowRunRequest) => {
      if (!workflowId) {
        toast.error('Save the workflow before running it.');
        return;
      }
      if (
        !canCode &&
        docRef.current.nodes.some((node) => node.type === 'code.run')
      ) {
        toast.error(
          'You need the workflows.code permission to run Code nodes.',
        );
        return;
      }
      setBusy(true);
      try {
        if (docDirty) {
          const saved = await onSave(); // run the latest draft
          if (!saved) return;
        }
        await workflowService.run(workflowId, request);
        setRunsReloadToken((t) => t + 1);
        setRunDialogOpen(false);
        toast.success('Run started - open the Logs tab to follow it.');
      } catch (e) {
        toast.error(e instanceof Error ? e.message : 'Run failed.');
      } finally {
        setBusy(false);
      }
    },
    [canCode, workflowId, docDirty, onSave],
  );

  const loadTestOptions = useCallback(async () => {
    if (!workflowId) return;
    setTestSources([]);
    setTestOptionsLoading(true);
    setTestOptionsError(false);
    try {
      const options = await workflowService.getTestOptions(workflowId);
      setTestSources(options.omnichannelTestSources);
    } catch {
      setTestOptionsError(true);
    } finally {
      setTestOptionsLoading(false);
    }
  }, [workflowId]);

  const onRun = useCallback(async () => {
    if (trigger?.type !== 'omnichannel.message_received') {
      if (
        triggerInputs.length > 0 ||
        runSideEffects.mutatesRedis ||
        runSideEffects.runsCode
      ) {
        setRunDialogOpen(true);
      } else {
        void doRun({ inputs: {} });
      }
      return;
    }

    if (runPreparationRef.current) return;
    runPreparationRef.current = true;
    setBusy(true);
    try {
      if (!workflowId) {
        await doRun({ inputs: {} });
        return;
      }
      const intendedDraft = docRef.current;
      if (docDirty) {
        const saved = await onSave();
        if (!saved || docRef.current !== intendedDraft) return;
      }
      await loadTestOptions();
      if (docRef.current !== intendedDraft) return;
      setRunDialogOpen(true);
    } finally {
      setBusy(false);
      runPreparationRef.current = false;
    }
  }, [
    trigger,
    triggerInputs,
    workflowId,
    docDirty,
    doRun,
    loadTestOptions,
    onSave,
    runSideEffects,
  ]);

  // ---- debug execution (staleness-aware, D16) ----
  const runDebug = useCallback(
    async (targetNodeId: string, staleIds: string[]) => {
      if (!workflowId || !debugRunId) return;
      if (
        !canCode &&
        docRef.current.nodes.some((node) => node.type === 'code.run')
      ) {
        toast.error(
          'You need the workflows.code permission to run Code nodes.',
        );
        return;
      }
      setDebugBusy(true);
      try {
        const result = await workflowService.debugExecute(workflowId, {
          runId: debugRunId,
          targetNodeId,
          scratch: Object.fromEntries(
            docRef.current.nodes.map((n) => [n.id, n.config]),
          ),
          staleNodeIds: staleIds,
        });
        setDebugCache((cache) => {
          const next = { ...(cache ?? {}) };
          for (const n of result.nodes) next[n.nodeId] = n;
          return next;
        });
        setDebugStale((s) => {
          const ns = new Set(s);
          result.nodes.forEach((n) => ns.delete(n.nodeId));
          return ns;
        });
      } catch (e) {
        toast.error(e instanceof Error ? e.message : 'Execution failed.');
      } finally {
        setDebugBusy(false);
      }
    },
    [canCode, workflowId, debugRunId],
  );

  const onExecuteAll = useCallback(() => {
    const ordered = topoOrder(docRef.current);
    const last = ordered[ordered.length - 1];
    if (last)
      void runDebug(
        last.id,
        docRef.current.nodes.map((n) => n.id),
      );
  }, [runDebug]);

  const exitDebug = useCallback(() => {
    if (workflowId) router.replace(`${workflowPath(workflowId)}?edit=1`);
  }, [router, workflowId]);

  const debugInEditor = useCallback(
    (runId: string) => {
      if (workflowId)
        router.push(`${workflowPath(workflowId)}?edit=1&debug=${runId}`);
    },
    [router, workflowId],
  );

  // Debug bundle for the canvas: cached outputs (stale nodes shown as pending).
  const debugBundle = useMemo<WorkflowDebugBundle | null>(() => {
    if (!debugCache) return null;
    const data: Record<string, WorkflowRunNode> = {};
    for (const [id, node] of Object.entries(debugCache)) {
      data[id] = debugStale.has(id) ? { ...node, status: 'pending' } : node;
    }
    return {
      data,
      busy: debugBusy,
      onExecuteNode: (nodeId: string) =>
        void runDebug(nodeId, Array.from(debugStale)),
    };
  }, [debugCache, debugStale, debugBusy, runDebug]);

  // Stable across renders (fix round 2, AC-DLA-30/31 D7) - see use-user-form.tsx.
  const fetchRecordAt = useCallback(
    (query: ListQuery, index: number) =>
      workflowService.getAt(query, index).then((r) => ({
        recordId: r.workflow?.id ?? null,
        total: r.total,
      })),
    [],
  );
  const buildRecordHref = useCallback(
    (recordId: string, ctx: string, index: number) => workflowFormHref(recordId, { ctx, index }),
    [],
  );

  const config = useMemo<ResourceFormConfig<Workflow> | null>(() => {
    if (!isNew && !workflow) return null;
    const editorWorkflow = workflow ?? blankWorkflow();
    return {
      breadcrumb: [
        { label: 'Workflows', href: WORKFLOWS_PATH },
        { label: isNew ? 'New workflow' : (workflow?.name ?? '') },
      ],
      backHref: WORKFLOWS_PATH,
      title: isNew ? 'New workflow' : (workflow?.name ?? ''),
      subtitle: isNew ? 'Automation' : undefined,
      tabs: [
        {
          id: 'editor',
          label: 'Editor',
          icon: WorkflowIcon,
          render: ({ editing }) => (
            <>
              <WorkflowEditorTab
                workflow={editorWorkflow}
                doc={doc}
                onDocChange={handleDocChange}
                editing={editing || Boolean(debugBundle)}
                canManage={canManage && !isNew}
                templateOptions={templateOptions}
                metadata={metadata}
                canCode={canCode}
                busy={busy}
                onPublish={onPublish}
                onUnpublish={onUnpublish}
                onRun={onRun}
                debug={debugBundle}
                onExecuteAll={onExecuteAll}
                onExitDebug={exitDebug}
              />
              <RunDialog
                open={runDialogOpen}
                onOpenChange={setRunDialogOpen}
                trigger={trigger}
                testSources={testSources}
                testOptionsLoading={testOptionsLoading}
                testOptionsError={testOptionsError}
                sideEffects={runSideEffects}
                codeRunnerAvailable={metadata.codeRunnerAvailable}
                busy={busy}
                onRun={doRun}
              />
            </>
          ),
        },
        {
          id: 'logs',
          label: 'Logs',
          icon: ScrollText,
          render: () =>
            isNew || !workflowId ? (
              <p className="py-12 text-center text-sm text-muted-foreground">
                Save and run the workflow to see its execution history.
              </p>
            ) : (
              <WorkflowRuns
                workflowId={workflowId}
                reloadToken={runsReloadToken}
                onDebugInEditor={debugInEditor}
              />
            ),
        },
        {
          id: 'settings',
          label: 'Settings',
          icon: FileText,
          render: ({ editing }) => (
            <WorkflowSettingsFields
              form={form}
              editing={editing}
              workflow={workflow}
              canManage={canManage}
              busy={busy}
              onSetActive={onSetActive}
              definition={doc}
              onDefinitionChange={handleDocChange}
              metadata={metadata}
            />
          ),
        },
        {
          id: 'versions',
          label: 'Versions',
          icon: History,
          render: () =>
            isNew || !workflowId ? (
              <p className="py-12 text-center text-sm text-muted-foreground">
                Publish the workflow to create its first version.
              </p>
            ) : (
              <WorkflowVersionsTab
                workflowId={workflowId}
                currentVersionId={workflow?.currentVersionId ?? null}
              />
            ),
        },
      ],
      initialTabId: 'editor',
      actions,
      actionRows: workflow ? [workflow] : [],
      editable: true,
      editPermission: 'workflows.manage',
      initialEditing: isNew ? true : initialEditing,
      isDirty: docDirty || form.formState.isDirty,
      onSave,
      onCancel,
      onReload: workflowId ? () => void refresh(workflowId) : undefined,
      recordNav: isNew
        ? undefined
        : { fetchAt: fetchRecordAt, buildHref: buildRecordHref },
    };
  }, [
    actions,
    busy,
    canManage,
    canCode,
    debugBundle,
    debugInEditor,
    doc,
    docDirty,
    doRun,
    exitDebug,
    form,
    handleDocChange,
    initialEditing,
    isNew,
    metadata,
    onCancel,
    onExecuteAll,
    onPublish,
    onRun,
    onSave,
    onSetActive,
    onUnpublish,
    refresh,
    runDialogOpen,
    runsReloadToken,
    runSideEffects,
    templateOptions,
    testOptionsError,
    testOptionsLoading,
    testSources,
    trigger,
    workflow,
    workflowId,
    fetchRecordAt,
    buildRecordHref,
  ]);

  return { config, form, isLoading, notFound };
}
