/**
 * In-memory mock for the workflow service (Phase A). Stateful across a session
 * so create/edit/publish/run feel real with no backend. Swapped out in Phase B.
 */
import { toCsv } from '@/lib/csv';
import { catalogEntry } from '@/lib/workflow-catalog';
import { createBlankDefinition, newId, topoOrder } from '@/lib/workflow-doc';
import type { ListQuery } from '@/types/resource';
import type {
  Workflow,
  WorkflowDebugRequest,
  WorkflowDefinition,
  WorkflowListItem,
  WorkflowRunDetail,
  WorkflowRunListItem,
  WorkflowRunNode,
  WorkflowRunRequest,
  WorkflowTestOptions,
  WorkflowVersionSummary,
} from '@/types/workflows';
import type { WorkflowService } from './workflow-service';

const LATENCY_MS = 220;
function delay<T>(value: T): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), LATENCY_MS));
}
function isoMinsAgo(n: number): string {
  return new Date(Date.now() - n * 60_000).toISOString();
}

// ---- seed ----

function welcomeDefinition(): WorkflowDefinition {
  return {
    schemaVersion: 1,
    nodes: [
      {
        id: 'trg_seed1',
        kind: 'trigger',
        type: 'manual',
        config: {
          inputs: [
            { key: 'email', label: 'Recipient email', type: 'string' },
            { key: 'name', label: 'Recipient name', type: 'string' },
          ],
        },
        position: { x: 40, y: 40 },
      },
      {
        id: 'act_seed1',
        kind: 'action',
        type: 'email.send',
        config: {
          templateId: 'tpl-welcome',
          to: '{{ trigger.input.email }}',
          subjectOverride: 'Welcome aboard, {{ trigger.input.name }}!',
        },
        position: { x: 40, y: 220 },
      },
    ],
    edges: [{ id: 'e_seed1', source: 'trg_seed1', target: 'act_seed1', sourcePort: 'out' }],
  };
}

interface StoredVersion {
  id: string;
  versionNumber: number;
  definition: WorkflowDefinition;
  publishedAt: string;
  publishedByName: string;
  notes: string | null;
}
interface StoredWorkflow {
  id: string;
  name: string;
  description: string;
  isActive: boolean;
  isTrashed: boolean;
  draftDefinition: WorkflowDefinition;
  currentVersionId: string | null;
  versions: StoredVersion[];
  createdByName: string;
  createdAt: string;
  updatedAt: string;
}

function seedWorkflows(): StoredWorkflow[] {
  const def = welcomeDefinition();
  const versionId = 'ver_seed1';
  return [
    {
      id: 'wf-welcome',
      name: 'Welcome email',
      description: 'Send a branded welcome email on demand.',
      isActive: true,
      isTrashed: false,
      draftDefinition: def,
      currentVersionId: versionId,
      versions: [
        {
          id: versionId,
          versionNumber: 1,
          definition: def,
          publishedAt: isoMinsAgo(180),
          publishedByName: 'Demo Admin',
          notes: null,
        },
      ],
      createdByName: 'Demo Admin',
      createdAt: isoMinsAgo(240),
      updatedAt: isoMinsAgo(120),
    },
    {
      id: 'wf-draft',
      name: 'Reminder blast (draft)',
      description: 'Work in progress - not published yet.',
      isActive: false,
      isTrashed: false,
      draftDefinition: createBlankDefinition(),
      currentVersionId: null,
      versions: [],
      createdByName: 'Demo Admin',
      createdAt: isoMinsAgo(60),
      updatedAt: isoMinsAgo(30),
    },
  ];
}

let WORKFLOWS = seedWorkflows();

interface StoredRun extends WorkflowRunDetail {
  workflowId: string;
}

function buildRunNodes(def: WorkflowDefinition, fail: boolean): WorkflowRunNode[] {
  const ordered = topoOrder(def);
  let failedYet = false;
  return ordered.map((node, i): WorkflowRunNode => {
    const entry = catalogEntry(node.type);
    if (failedYet) {
      return {
        nodeId: node.id,
        nodeType: node.type,
        status: 'skipped',
        inputJson: null,
        outputJson: null,
        error: null,
        startedAt: null,
        finishedAt: null,
      };
    }
    const isLast = i === ordered.length - 1;
    if (fail && isLast) {
      failedYet = true;
      return {
        nodeId: node.id,
        nodeType: node.type,
        status: 'failed',
        inputJson: { to: 'alex@example.com' },
        outputJson: null,
        error: 'SMTPConnectError: connection refused by smtp.acme.com:587',
        startedAt: isoMinsAgo(2),
        finishedAt: isoMinsAgo(2),
      };
    }
    const output =
      node.kind === 'trigger'
        ? { triggeredBy: 'manual', 'trigger.input.email': 'alex@example.com', 'trigger.input.name': 'Alex Tan' }
        : entry?.type === 'email.send'
          ? { messageId: newId('eml'), status: 'queued' }
          : {};
    return {
      nodeId: node.id,
      nodeType: node.type,
      status: 'success',
      inputJson: node.kind === 'trigger' ? null : { to: 'alex@example.com' },
      outputJson: output,
      error: null,
      startedAt: isoMinsAgo(3),
      finishedAt: isoMinsAgo(3),
    };
  });
}

function seedRuns(): StoredRun[] {
  const wf = WORKFLOWS[0];
  const def = wf.versions[0].definition;
  const make = (n: number, fail: boolean): StoredRun => {
    const nodes = buildRunNodes(def, fail);
    return {
      id: newId('run'),
      workflowId: wf.id,
      status: fail ? 'failed' : 'success',
      triggeredBy: 'manual',
      isTest: n === 0,
      actorName: 'Demo Admin',
      startedAt: isoMinsAgo(n * 30 + 5),
      finishedAt: isoMinsAgo(n * 30 + 5),
      durationMs: 1240 + n * 60,
      versionNumber: 1,
      error: fail ? 'Node "Send email" failed.' : null,
      createdAt: isoMinsAgo(n * 30 + 5),
      definition: def,
      triggerPayload: { input: { email: 'alex@example.com', name: 'Alex Tan' } },
      nodes,
    };
  };
  return [make(0, false), make(1, false), make(2, true), make(3, false)];
}

let RUNS = seedRuns();

function toRunSummary(run: StoredRun): WorkflowRunListItem {
  return {
    id: run.id,
    status: run.status,
    triggeredBy: run.triggeredBy,
    isTest: run.isTest,
    actorName: run.actorName,
    startedAt: run.startedAt,
    finishedAt: run.finishedAt,
    durationMs: run.durationMs,
    versionNumber: run.versionNumber,
    error: run.error,
    createdAt: run.createdAt,
  };
}

function toRunDetail(run: StoredRun): WorkflowRunDetail {
  return {
    ...toRunSummary(run),
    definition: run.definition,
    triggerPayload: run.triggerPayload,
    nodes: run.nodes,
  };
}

// ---- list helpers ----

function toListItem(wf: StoredWorkflow): WorkflowListItem {
  const trigger = wf.draftDefinition.nodes.find((n) => n.kind === 'trigger');
  const triggerLabel = trigger ? (catalogEntry(trigger.type)?.label ?? trigger.type) : '-';
  const lastRun = RUNS.filter((r) => r.workflowId === wf.id).sort((a, b) =>
    b.createdAt.localeCompare(a.createdAt),
  )[0];
  const current = wf.versions.find((v) => v.id === wf.currentVersionId);
  return {
    id: wf.id,
    name: wf.name,
    description: wf.description,
    isActive: wf.isActive,
    isTrashed: wf.isTrashed,
    triggerType: trigger?.type ?? '',
    triggerLabel,
    currentVersionNumber: current?.versionNumber ?? null,
    hasUnpublishedChanges: hasUnpublished(wf),
    lastRunAt: lastRun?.createdAt ?? null,
    lastRunStatus: lastRun?.status ?? null,
    updatedAt: wf.updatedAt,
  };
}

function hasUnpublished(wf: StoredWorkflow): boolean {
  if (!wf.currentVersionId) return wf.draftDefinition.nodes.length > 0;
  const current = wf.versions.find((v) => v.id === wf.currentVersionId);
  return JSON.stringify(current?.definition) !== JSON.stringify(wf.draftDefinition);
}

function versionSummary(v: StoredVersion): WorkflowVersionSummary {
  return {
    id: v.id,
    versionNumber: v.versionNumber,
    publishedAt: v.publishedAt,
    publishedByName: v.publishedByName,
    notes: v.notes,
  };
}

function toWorkflow(wf: StoredWorkflow): Workflow {
  const listItem = toListItem(wf);
  const current = wf.versions.find((v) => v.id === wf.currentVersionId) ?? null;
  return {
    ...listItem,
    draftDefinition: wf.draftDefinition,
    currentVersionId: wf.currentVersionId,
    currentVersion: current ? versionSummary(current) : null,
    createdByName: wf.createdByName,
    createdAt: wf.createdAt,
  };
}

function applyQuery(items: WorkflowListItem[], query: ListQuery): WorkflowListItem[] {
  // Active|Archived view (statusView: 'trashed' = archived).
  let rows = items.filter((r) => (query.statusView === 'trashed' ? r.isTrashed : !r.isTrashed));
  if (query.search) {
    const q = query.search.toLowerCase();
    rows = rows.filter(
      (r) => r.name.toLowerCase().includes(q) || r.description.toLowerCase().includes(q),
    );
  }
  if (query.sort) {
    const { id, desc } = query.sort;
    rows.sort((a, b) => {
      const av = String((a as unknown as Record<string, unknown>)[id] ?? '');
      const bv = String((b as unknown as Record<string, unknown>)[id] ?? '');
      return desc ? bv.localeCompare(av) : av.localeCompare(bv);
    });
  }
  return rows;
}

// ---- service ----

export const mockWorkflowService: WorkflowService = {
  list(query) {
    const all = applyQuery(WORKFLOWS.map(toListItem), query);
    const start = query.page * query.pageSize;
    return delay({ data: all.slice(start, start + query.pageSize), total: all.length, page: query.page });
  },

  getAt(query, index) {
    const all = applyQuery(WORKFLOWS.map(toListItem), query);
    return delay({ workflow: all[index] ?? null, total: all.length });
  },

  get(id) {
    const wf = WORKFLOWS.find((w) => w.id === id);
    return delay(wf ? toWorkflow(wf) : null);
  },

  create(input) {
    const now = new Date().toISOString();
    const wf: StoredWorkflow = {
      id: newId('wf'),
      name: input.name,
      description: input.description,
      isActive: false,
      isTrashed: false,
      draftDefinition: input.draftDefinition,
      currentVersionId: null,
      versions: [],
      createdByName: 'Demo Admin',
      createdAt: now,
      updatedAt: now,
    };
    WORKFLOWS = [wf, ...WORKFLOWS];
    return delay(toWorkflow(wf));
  },

  update(id, input) {
    const wf = WORKFLOWS.find((w) => w.id === id);
    if (!wf) return Promise.reject(new Error('Workflow not found.'));
    wf.name = input.name;
    wf.description = input.description;
    wf.draftDefinition = input.draftDefinition;
    wf.updatedAt = new Date().toISOString();
    return delay(toWorkflow(wf));
  },

  remove(id) {
    WORKFLOWS = WORKFLOWS.filter((w) => w.id !== id);
    RUNS = RUNS.filter((r) => r.workflowId !== id);
    return delay(undefined);
  },

  duplicate(id) {
    const wf = WORKFLOWS.find((w) => w.id === id);
    if (!wf) return Promise.reject(new Error('Workflow not found.'));
    const now = new Date().toISOString();
    const copy: StoredWorkflow = {
      ...wf,
      id: newId('wf'),
      name: `${wf.name} (copy)`,
      isActive: false,
      isTrashed: false,
      currentVersionId: null,
      versions: [],
      draftDefinition: JSON.parse(JSON.stringify(wf.draftDefinition)),
      createdAt: now,
      updatedAt: now,
    };
    WORKFLOWS = [copy, ...WORKFLOWS];
    return delay(toWorkflow(copy));
  },

  setActive(id, isActive) {
    const wf = WORKFLOWS.find((w) => w.id === id);
    if (!wf) return Promise.reject(new Error('Workflow not found.'));
    wf.isActive = isActive;
    wf.updatedAt = new Date().toISOString();
    return delay(toWorkflow(wf));
  },

  archive(id) {
    const wf = WORKFLOWS.find((w) => w.id === id);
    if (!wf) return Promise.reject(new Error('Workflow not found.'));
    wf.isTrashed = true;
    wf.isActive = false; // archived workflows never fire
    wf.updatedAt = new Date().toISOString();
    return delay(toWorkflow(wf));
  },

  restore(id) {
    const wf = WORKFLOWS.find((w) => w.id === id);
    if (!wf) return Promise.reject(new Error('Workflow not found.'));
    wf.isTrashed = false;
    wf.updatedAt = new Date().toISOString();
    return delay(toWorkflow(wf));
  },

  publish(id) {
    const wf = WORKFLOWS.find((w) => w.id === id);
    if (!wf) return Promise.reject(new Error('Workflow not found.'));
    const versionNumber = (wf.versions[wf.versions.length - 1]?.versionNumber ?? 0) + 1;
    const version: StoredVersion = {
      id: newId('ver'),
      versionNumber,
      definition: JSON.parse(JSON.stringify(wf.draftDefinition)),
      publishedAt: new Date().toISOString(),
      publishedByName: 'Demo Admin',
      notes: null,
    };
    wf.versions = [...wf.versions, version];
    wf.currentVersionId = version.id;
    wf.updatedAt = version.publishedAt;
    return delay(toWorkflow(wf));
  },

  unpublish(id) {
    const wf = WORKFLOWS.find((w) => w.id === id);
    if (!wf) return Promise.reject(new Error('Workflow not found.'));
    wf.currentVersionId = null;
    wf.updatedAt = new Date().toISOString();
    return delay(toWorkflow(wf));
  },

  run(id, request: WorkflowRunRequest) {
    const wf = WORKFLOWS.find((w) => w.id === id);
    if (!wf) return Promise.reject(new Error('Workflow not found.'));
    // Manual run executes the current DRAFT - no publish required (D13).
    const version = wf.versions.find((v) => v.id === wf.currentVersionId);
    const definition = wf.draftDefinition;
    const now = new Date().toISOString();
    const nodes = buildRunNodes(definition, false);
    const run: StoredRun = {
      id: newId('run'),
      workflowId: id,
      status: 'success',
      triggeredBy: 'manual',
      isTest: Boolean(request.isTest),
      actorName: 'Demo Admin',
      startedAt: now,
      finishedAt: now,
      durationMs: 1180,
      versionNumber: version?.versionNumber ?? 0, // 0 = ran the draft
      error: null,
      createdAt: now,
      definition,
      triggerPayload: { input: request.inputs },
      nodes,
    };
    RUNS = [run, ...RUNS];
    return delay(toRunSummary(run));
  },

  getTestOptions(): Promise<WorkflowTestOptions> {
    return delay({
      omnichannelTestSources: [
        {
          channelId: 'chn-demo',
          channelName: 'Demo sandbox',
          contactId: 'cnt-001',
          contactName: 'Alice',
          contactPhone: '+6012',
        },
      ],
    });
  },

  listRuns(workflowId, query) {
    let rows = RUNS.filter((r) => r.workflowId === workflowId).map(toRunSummary);
    if (query.segment && query.segment !== 'all') {
      rows = rows.filter((r) => r.status === query.segment);
    }
    rows.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    const start = query.page * query.pageSize;
    return delay({ data: rows.slice(start, start + query.pageSize), total: rows.length, page: query.page });
  },

  getRun(runId) {
    const run = RUNS.find((r) => r.id === runId);
    return delay(run ? toRunDetail(run) : null);
  },

  listVersions(workflowId, query) {
    const wf = WORKFLOWS.find((w) => w.id === workflowId);
    const all = (wf?.versions ?? [])
      .map(versionSummary)
      .sort((a, b) => b.versionNumber - a.versionNumber);
    const start = query.page * query.pageSize;
    return delay({ data: all.slice(start, start + query.pageSize), total: all.length, page: query.page });
  },

  cancelRun(runId) {
    const run = RUNS.find((r) => r.id === runId);
    if (!run) return Promise.reject(new Error('Run not found.'));
    if (run.status !== 'pending' && run.status !== 'running') {
      return Promise.reject(new Error('Only pending or running runs can be cancelled.'));
    }
    run.status = 'cancelled';
    return delay(toRunSummary(run));
  },

  debugExecute(_workflowId, request: WorkflowDebugRequest) {
    const run = RUNS.find((r) => r.id === request.runId);
    if (!run) return Promise.reject(new Error('Run not found.'));
    // Re-run the stale set up to the target: anything stale/uncached on the
    // path re-executes; everything else reuses its cached output (D16). The
    // mock just re-emits fresh outputs for the target + its stale ancestors.
    const stale = new Set(request.staleNodeIds);
    const ordered = topoOrder(run.definition);
    const targetIdx = ordered.findIndex((n) => n.id === request.targetNodeId);
    const touched: WorkflowRunNode[] = [];
    for (let i = 0; i <= targetIdx; i++) {
      const node = ordered[i];
      const cached = run.nodes.find((rn) => rn.nodeId === node.id);
      const mustRun = node.id === request.targetNodeId || stale.has(node.id) || !cached?.outputJson;
      if (!mustRun) continue;
      const entry = catalogEntry(node.type);
      const output =
        node.kind === 'trigger'
          ? { triggeredBy: 'manual', ...(run.triggerPayload as Record<string, unknown>) }
          : entry?.type === 'email.send'
            ? { messageId: newId('eml'), status: 'queued' }
            : {};
      const fresh: WorkflowRunNode = {
        nodeId: node.id,
        nodeType: node.type,
        status: 'success',
        inputJson: node.kind === 'trigger' ? null : { to: 'alex@example.com' },
        outputJson: output,
        error: null,
        startedAt: new Date().toISOString(),
        finishedAt: new Date().toISOString(),
      };
      touched.push(fresh);
    }
    return delay({ nodes: touched });
  },

  listTemplateOptions() {
    return delay([
      { value: 'tpl-welcome', label: 'Welcome email' },
      { value: 'tpl-reset', label: 'Password reset' },
      { value: 'tpl-invite', label: 'Team invitation' },
      { value: 'tpl-announce', label: 'Announcement' },
    ]);
  },

  getSettings() {
    return delay({ runRetentionDays: 30, isDefault: true });
  },

  updateSettings(runRetentionDays: number) {
    return delay({ runRetentionDays, isDefault: false });
  },

  export(query, columns) {
    const rows = applyQuery(WORKFLOWS.map(toListItem), query);
    const body = rows.map((r) =>
      columns.map((c) => String((r as unknown as Record<string, unknown>)[c] ?? '')),
    );
    return delay(toCsv(columns, body));
  },
};
