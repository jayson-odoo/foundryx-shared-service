/**
 * Pure helpers over the workflow definition doc (plan sprint-2/08 D3) - the
 * editor-agnostic graph contract. All functions are immutable (return a new
 * doc) so undo/redo can keep a history of snapshots, exactly like the email
 * editor's block-doc helpers.
 */
import type {
  WorkflowAiOutputParam,
  WorkflowDefinition,
  WorkflowEdge,
  WorkflowExecution,
  WorkflowNode,
  WorkflowNodeConfig,
  WorkflowNodeKind,
} from '@/types/workflows';
import { catalogEntry, isTriggerType } from '@/lib/workflow-catalog';
import { pythonSyntaxIssues } from '@/lib/python-diagnostics';

export const WORKFLOW_SCHEMA_VERSION = 2;

// Conservative ASCII identifier grammar. Output keys are inserted into merge
// paths as `nodes.<id>.<key>` and must remain one merge-token segment.
export const AI_OUTPUT_PARAM_KEY_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;
export const AI_OUTPUT_PARAM_TYPES = [
  'string',
  'number',
  'boolean',
  'enum',
] as const;
const AI_OUTPUT_PARAM_PREFIX = 'AI Agent: "Output parameters"';
export const CORRELATION_KEY_RE = /^\{\{\s*[A-Za-z_][A-Za-z0-9_.]*\s*\}\}$/;

export function codeSourceIssues(source: string): string[] {
  const issues: string[] = pythonSyntaxIssues(source);
  const forbidden = /(^|\s)(import|from)\s|\b(exec|eval|__import__)\s*\(/;
  const forbiddenLine = source
    .split(/\r?\n/)
    .findIndex((line) => forbidden.test(line));
  if (forbiddenLine >= 0)
    issues.push(`Unsupported syntax on line ${forbiddenLine + 1}.`);
  const pairs: Array<[string, string]> = [
    ['(', ')'],
    ['[', ']'],
    ['{', '}'],
  ];
  for (const [opening, closing] of pairs) {
    if (
      source.split('').filter((character) => character === opening).length !==
      source.split('').filter((character) => character === closing).length
    ) {
      issues.push(`Unbalanced ${opening}${closing} delimiters.`);
    }
  }
  if (source.trim()) {
    const assignment = source.match(/\bresult\s*=\s*([^\r\n]*)/);
    if (!assignment) {
      issues.push('Code must assign a result dictionary.');
    } else if (!assignment[1].trim()) {
      issues.push('Result assignment must include a value.');
    }
  }
  return issues;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function outputParamIssues(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [
      `${AI_OUTPUT_PARAM_PREFIX} must be a non-empty list of parameter objects.`,
    ];
  }
  if (!value.length) {
    return [`${AI_OUTPUT_PARAM_PREFIX} must contain at least one parameter.`];
  }

  const issues: string[] = [];
  const seen = new Set<string>();
  for (const row of value) {
    if (!isRecord(row)) {
      issues.push(
        `${AI_OUTPUT_PARAM_PREFIX} contains a parameter that is not an object.`,
      );
      continue;
    }
    const key = row.key;
    if (typeof key !== 'string' || !key.trim()) {
      issues.push(
        `${AI_OUTPUT_PARAM_PREFIX} contains a parameter without a key.`,
      );
      continue;
    }
    if (key !== key.trim()) {
      issues.push(
        `${AI_OUTPUT_PARAM_PREFIX} contains a key with surrounding whitespace.`,
      );
      continue;
    }
    if (!AI_OUTPUT_PARAM_KEY_RE.test(key)) {
      issues.push(
        `${AI_OUTPUT_PARAM_PREFIX} contains an invalid key "${key}". ` +
          'Use letters, numbers, and underscores; start with a letter or underscore.',
      );
    } else if (seen.has(key)) {
      issues.push(`${AI_OUTPUT_PARAM_PREFIX} contains duplicate key "${key}".`);
    } else {
      seen.add(key);
    }
    if (
      typeof row.type !== 'string' ||
      !AI_OUTPUT_PARAM_TYPES.includes(
        row.type as (typeof AI_OUTPUT_PARAM_TYPES)[number],
      )
    ) {
      issues.push(
        `${AI_OUTPUT_PARAM_PREFIX} contains a parameter with an invalid type.`,
      );
    }
    if (row.type === 'enum') {
      const values = row.enumValues;
      if (!Array.isArray(values) || values.length < 2) {
        issues.push(
          `${AI_OUTPUT_PARAM_PREFIX} enum parameters need at least two values.`,
        );
      } else {
        const enumSeen = new Set<string>();
        for (const item of values) {
          if (typeof item !== 'string' || !item.trim()) {
            issues.push(
              `${AI_OUTPUT_PARAM_PREFIX} enum values cannot be blank.`,
            );
          } else if (enumSeen.has(item)) {
            issues.push(
              `${AI_OUTPUT_PARAM_PREFIX} enum values must be unique.`,
            );
          } else {
            enumSeen.add(item);
          }
        }
      }
    } else if (row.enumValues !== undefined) {
      issues.push(
        `${AI_OUTPUT_PARAM_PREFIX} enum values are only valid for Enum parameters.`,
      );
    }
  }
  return issues;
}

export function validAiOutputParams(value: unknown): WorkflowAiOutputParam[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const valid: WorkflowAiOutputParam[] = [];
  for (const row of value) {
    if (!isRecord(row)) continue;
    const key = row.key;
    const type = row.type;
    if (
      typeof key !== 'string' ||
      key !== key.trim() ||
      !AI_OUTPUT_PARAM_KEY_RE.test(key) ||
      typeof type !== 'string' ||
      !AI_OUTPUT_PARAM_TYPES.includes(
        type as (typeof AI_OUTPUT_PARAM_TYPES)[number],
      ) ||
      seen.has(key)
    ) {
      continue;
    }
    seen.add(key);
    valid.push({
      key,
      type: type as WorkflowAiOutputParam['type'],
      ...(type === 'enum' && Array.isArray(row.enumValues)
        ? {
            enumValues: row.enumValues.filter(
              (v): v is string => typeof v === 'string',
            ),
          }
        : {}),
      ...(typeof row.description === 'string'
        ? { description: row.description }
        : {}),
      ...(typeof row.required === 'boolean' ? { required: row.required } : {}),
      ...(typeof row.stateful === 'boolean' ? { stateful: row.stateful } : {}),
    });
  }
  return valid;
}

/** Stable short id for nodes/edges (forever-contract ids). */
export function newId(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 8)}`;
}

export function createBlankDefinition(): WorkflowDefinition {
  return {
    schemaVersion: WORKFLOW_SCHEMA_VERSION,
    execution: { mode: 'parallel', correlationKey: '' },
    nodes: [],
    edges: [],
  };
}

/** Read old drafts without mutating the source. Missing execution data keeps
 * the v1 parallel behavior and omitted stateful flags remain transient. */
export function migrateWorkflowDefinition(value: unknown): WorkflowDefinition {
  if (!isRecord(value)) return createBlankDefinition();
  const nodes = Array.isArray(value.nodes) ? value.nodes : [];
  const edges = Array.isArray(value.edges) ? value.edges : [];
  const execution = isRecord(value.execution)
    ? {
        mode: value.execution.mode === 'serialized' ? 'serialized' : 'parallel',
        correlationKey:
          typeof value.execution.correlationKey === 'string'
            ? value.execution.correlationKey
            : '',
      }
    : { mode: 'parallel', correlationKey: '' };
  return {
    schemaVersion: WORKFLOW_SCHEMA_VERSION,
    execution: execution as WorkflowExecution,
    nodes: nodes as WorkflowDefinition['nodes'],
    edges: edges as WorkflowDefinition['edges'],
  };
}

/** Alias used by callers that want to make v1 compatibility explicit. */
export const normalizeWorkflowDefinition = migrateWorkflowDefinition;

/** Default config for a freshly-dropped node of `type`. */
function defaultConfig(type: string): WorkflowNodeConfig {
  if (type === 'manual') return { inputs: [] };
  if (type === 'email.send') return { mode: 'template' };
  if (type === 'entity.field_changed') return { entityType: '', field: '' };
  if (type === 'entity.status_changed')
    return { entityType: '', fromStatus: '', toStatus: '' };
  if (type === 'entity.transition_status')
    return { entityType: '', recordId: '', toStatus: '' };
  if (type === 'entity.update')
    return { entityType: '', recordId: '', assignments: [] };
  if (type.startsWith('entity.')) return { entityType: '' };
  if (type === 'form.submitted') return { formId: '' };
  if (type === 'schedule.cron') return { cron: '0 9 * * *', timezone: '' };
  if (type === 'if') return { conditions: null };
  // Omnichannel + AI Agent nodes (plan sprint-4/17).
  if (type === 'omnichannel.message_received') return { channelId: null };
  if (type === 'omnichannel.get_contact') return { contactId: '' };
  if (type === 'omnichannel.send_message')
    return { contactId: '', message: '' };
  if (type === 'ai_agent.run')
    return { agentId: '', instructions: '', inputText: '', outputParams: [] };
  if (type === 'ai_agent.clear_state') return { agentNodeId: '' };
  if (type === 'ai_agent.read_state') return { agentNodeId: '' };
  if (type === 'redis.command') return { operation: 'get', key: '' };
  if (type === 'code.run') {
    return {
      language: 'python',
      source: '',
      inputs: [],
      outputs: [],
    };
  }
  return {};
}

export function createNode(
  type: string,
  position: { x: number; y: number },
): WorkflowNode {
  const entry = catalogEntry(type);
  const kind: WorkflowNodeKind =
    entry?.kind ?? (isTriggerType(type) ? 'trigger' : 'action');
  return {
    id: newId(kind === 'trigger' ? 'trg' : kind === 'action' ? 'act' : 'if'),
    kind,
    type,
    config: defaultConfig(type),
    position,
  };
}

export function hasTrigger(doc: WorkflowDefinition): boolean {
  return doc.nodes.some((n) => n.kind === 'trigger');
}

/** A node's display name - the user-set `config.name`, else the catalog label.
 * Names disambiguate two same-type nodes (n8n behavior); refs stay id-based so
 * a rename never breaks an expression. */
export function nodeDisplayName(
  node: WorkflowNode,
  fallbackLabel: string,
): string {
  const name = node.config?.name;
  return typeof name === 'string' && name.trim() ? name.trim() : fallbackLabel;
}

/** A default node name unique within the doc - appends " 2", " 3"… on clash so
 * every node is identifiable in the dynamic-content picker. */
export function uniqueNodeName(doc: WorkflowDefinition, base: string): string {
  const used = new Set(
    doc.nodes.map((n) =>
      nodeDisplayName(n, catalogEntry(n.type)?.label ?? n.type),
    ),
  );
  if (!used.has(base)) return base;
  let i = 2;
  while (used.has(`${base} ${i}`)) i++;
  return `${base} ${i}`;
}

export function addNode(
  doc: WorkflowDefinition,
  node: WorkflowNode,
): WorkflowDefinition {
  return { ...doc, nodes: [...doc.nodes, node] };
}

export function removeNode(
  doc: WorkflowDefinition,
  nodeId: string,
): WorkflowDefinition {
  return {
    ...doc,
    nodes: doc.nodes.filter((n) => n.id !== nodeId),
    // Drop any edge touching the removed node.
    edges: doc.edges.filter((e) => e.source !== nodeId && e.target !== nodeId),
  };
}

export function updateNodeConfig(
  doc: WorkflowDefinition,
  nodeId: string,
  patch: WorkflowNodeConfig,
): WorkflowDefinition {
  return {
    ...doc,
    nodes: doc.nodes.map((n) =>
      n.id === nodeId ? { ...n, config: { ...n.config, ...patch } } : n,
    ),
  };
}

/** Swap a node's catalog type in place (quick replace / change trigger) -
 * resets config to the new type's defaults but keeps the node id, position,
 * name and (same-kind) edges. */
export function replaceNodeType(
  doc: WorkflowDefinition,
  nodeId: string,
  newType: string,
): WorkflowDefinition {
  const entry = catalogEntry(newType);
  const kind: WorkflowNodeKind =
    entry?.kind ?? (isTriggerType(newType) ? 'trigger' : 'action');
  return {
    ...doc,
    nodes: doc.nodes.map((n) =>
      n.id === nodeId
        ? {
            ...n,
            type: newType,
            kind,
            config: { ...defaultConfig(newType), name: n.config.name },
          }
        : n,
    ),
  };
}

export function moveNode(
  doc: WorkflowDefinition,
  nodeId: string,
  position: { x: number; y: number },
): WorkflowDefinition {
  return {
    ...doc,
    nodes: doc.nodes.map((n) => (n.id === nodeId ? { ...n, position } : n)),
  };
}

export function setPositions(
  doc: WorkflowDefinition,
  positions: Record<string, { x: number; y: number }>,
): WorkflowDefinition {
  return {
    ...doc,
    nodes: doc.nodes.map((n) =>
      positions[n.id] ? { ...n, position: positions[n.id] } : n,
    ),
  };
}

/** Would adding source→target create a cycle? (DAG invariant, D17.) */
export function wouldCreateCycle(
  doc: WorkflowDefinition,
  source: string,
  target: string,
): boolean {
  if (source === target) return true;
  // DFS from `target`; if we can reach `source`, the new edge closes a loop.
  const adjacency = new Map<string, string[]>();
  for (const e of doc.edges) {
    adjacency.set(e.source, [...(adjacency.get(e.source) ?? []), e.target]);
  }
  const seen = new Set<string>();
  const stack = [target];
  while (stack.length) {
    const current = stack.pop()!;
    if (current === source) return true;
    if (seen.has(current)) continue;
    seen.add(current);
    stack.push(...(adjacency.get(current) ?? []));
  }
  return false;
}

export function addEdge(
  doc: WorkflowDefinition,
  edge: Omit<WorkflowEdge, 'id'>,
): WorkflowDefinition {
  // A source port fans out to multiple targets (the executor already runs
  // every out-edge). Stay idempotent for an exact duplicate connection
  // (same source + port + target) so re-dragging an existing wire never
  // creates a second identical edge.
  const port = edge.sourcePort ?? 'out';
  const exists = doc.edges.some(
    (e) =>
      e.source === edge.source &&
      (e.sourcePort ?? 'out') === port &&
      e.target === edge.target,
  );
  if (exists) return doc;
  return {
    ...doc,
    edges: [...doc.edges, { ...edge, id: newId('e'), sourcePort: port }],
  };
}

export function removeEdge(
  doc: WorkflowDefinition,
  edgeId: string,
): WorkflowDefinition {
  return { ...doc, edges: doc.edges.filter((e) => e.id !== edgeId) };
}

/** Remove multiple edges in one pass (fixes the multi-select delete bug -
 * calling `removeEdge` per id against the same captured doc drops only the
 * last removal). Unknown ids are ignored. */
export function removeEdges(
  doc: WorkflowDefinition,
  edgeIds: string[],
): WorkflowDefinition {
  const ids = new Set(edgeIds);
  return { ...doc, edges: doc.edges.filter((e) => !ids.has(e.id)) };
}

/** Topological order from the trigger; nodes unreachable from it trail at the
 * end (the publish validator flags those - D17). */
export function topoOrder(doc: WorkflowDefinition): WorkflowNode[] {
  const indegree = new Map<string, number>(doc.nodes.map((n) => [n.id, 0]));
  for (const e of doc.edges)
    indegree.set(e.target, (indegree.get(e.target) ?? 0) + 1);
  const queue = doc.nodes
    .filter((n) => (indegree.get(n.id) ?? 0) === 0)
    .map((n) => n.id);
  const adjacency = new Map<string, string[]>();
  for (const e of doc.edges) {
    adjacency.set(e.source, [...(adjacency.get(e.source) ?? []), e.target]);
  }
  const order: string[] = [];
  const seen = new Set<string>();
  while (queue.length) {
    const id = queue.shift()!;
    if (seen.has(id)) continue;
    seen.add(id);
    order.push(id);
    for (const next of adjacency.get(id) ?? []) {
      indegree.set(next, (indegree.get(next) ?? 0) - 1);
      if ((indegree.get(next) ?? 0) <= 0) queue.push(next);
    }
  }
  const byId = new Map(doc.nodes.map((n) => [n.id, n]));
  const ordered = order.map((id) => byId.get(id)!).filter(Boolean);
  // Append any nodes not reached (disconnected/cyclic) so callers still see them.
  for (const n of doc.nodes) if (!seen.has(n.id)) ordered.push(n);
  return ordered;
}

export interface DefinitionIssue {
  level: 'error' | 'warning';
  message: string;
  nodeId?: string;
}

/** Mirror of the backend `validate_definition` (D17) - surfaced live in the
 * editor so publish failures are visible before the click. */
export function validateDefinition(
  doc: WorkflowDefinition,
  metadata?: { codeRunnerAvailable?: boolean },
): DefinitionIssue[] {
  void metadata;
  const issues: DefinitionIssue[] = [];
  const triggers = doc.nodes.filter((n) => n.kind === 'trigger');
  if (triggers.length === 0)
    issues.push({
      level: 'error',
      message: 'Add a trigger to start the workflow.',
    });
  if (triggers.length > 1)
    issues.push({
      level: 'error',
      message: 'A workflow can have only one trigger.',
    });

  const trigger = triggers[0];
  const execution = doc.execution;
  const statefulAgent = doc.nodes.some(
    (node) =>
      node.type === 'ai_agent.run' &&
      validAiOutputParams(node.config.outputParams).some(
        (param) => param.stateful,
      ),
  );
  const correlationKey = execution?.correlationKey?.trim() ?? '';
  if (
    execution?.mode === 'serialized' &&
    (!correlationKey || !CORRELATION_KEY_RE.test(correlationKey))
  ) {
    issues.push({
      level: 'error',
      message: 'Serialized execution requires a valid Correlation key.',
    });
  }
  if (statefulAgent && (execution?.mode !== 'serialized' || !correlationKey)) {
    issues.push({
      level: 'error',
      message:
        'Stateful AI Agent outputs require serialized execution and a Correlation key.',
    });
  }
  if (trigger && doc.edges.some((e) => e.target === trigger.id)) {
    issues.push({
      level: 'error',
      message: 'The trigger cannot have an incoming connection.',
      nodeId: trigger.id,
    });
  }

  // Unique node names - refs are id-based but a duplicate name is ambiguous in
  // the dynamic-content picker (user mandate: no replicated names).
  const nameCount = new Map<string, number>();
  for (const n of doc.nodes) {
    const nm = nodeDisplayName(n, catalogEntry(n.type)?.label ?? n.type);
    nameCount.set(nm, (nameCount.get(nm) ?? 0) + 1);
  }
  const flagged = new Set<string>();
  for (const n of doc.nodes) {
    const nm = nodeDisplayName(n, catalogEntry(n.type)?.label ?? n.type);
    if ((nameCount.get(nm) ?? 0) > 1) {
      if (!flagged.has(nm)) {
        issues.push({
          level: 'error',
          message: `Two nodes are named "${nm}" - names must be unique.`,
          nodeId: n.id,
        });
        flagged.add(nm);
      }
    }
  }

  // Reachability from the trigger (orphans block - D17).
  if (trigger) {
    const reachable = new Set<string>([trigger.id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const e of doc.edges) {
        if (reachable.has(e.source) && !reachable.has(e.target)) {
          reachable.add(e.target);
          grew = true;
        }
      }
    }
    for (const n of doc.nodes) {
      if (!reachable.has(n.id)) {
        issues.push({
          level: 'error',
          message: 'Node is not connected to the trigger.',
          nodeId: n.id,
        });
      }
    }
  }

  // Required config per node (catalog-driven).
  for (const n of doc.nodes) {
    const entry = catalogEntry(n.type);
    if (!entry) continue;
    for (const field of entry.fields) {
      if (
        field.showWhen &&
        n.config[field.showWhen.field] !== field.showWhen.value
      ) {
        continue; // hidden field - don't require it
      }
      if (field.required) {
        const value = n.config[field.key];
        const empty =
          value === undefined ||
          value === null ||
          value === '' ||
          (Array.isArray(value) && value.length === 0);
        if (field.type === 'outputSchema') {
          if (value === undefined || value === null || value === '') {
            issues.push({
              level: 'error',
              message: `${entry.label}: "${field.label}" is required.`,
              nodeId: n.id,
            });
          } else {
            for (const message of outputParamIssues(value)) {
              issues.push({ level: 'error', message, nodeId: n.id });
            }
          }
        } else if (empty) {
          issues.push({
            level: 'error',
            message: `${entry.label}: "${field.label}" is required.`,
            nodeId: n.id,
          });
        }
      }
    }
    // Connection-resolvability warning (warn-not-block, D17) needs real
    // connection data - added in Phase B.
    if (n.type === 'code.run' && typeof n.config.source === 'string') {
      for (const message of codeSourceIssues(n.config.source)) {
        issues.push({
          level: 'error',
          message: `Code: ${message}`,
          nodeId: n.id,
        });
      }
    }
    if (n.type === 'redis.command') {
      for (const message of redisConfigIssues(n.config)) {
        issues.push({ level: 'error', message, nodeId: n.id });
      }
    }
    // Read Agent State must point at a stateful AI Agent that exists in the
    // graph (parity with backend definition_issues; the required check above
    // already blocks an empty selection).
    if (n.type === 'ai_agent.read_state') {
      const targetId = n.config.agentNodeId;
      if (typeof targetId === 'string' && targetId) {
        const target = doc.nodes.find((t) => t.id === targetId);
        const ok =
          target?.type === 'ai_agent.run' &&
          validAiOutputParams(target.config.outputParams).some(
            (param) => param.stateful,
          );
        if (!ok) {
          issues.push({
            level: 'error',
            message:
              'Read Agent State must reference a stateful AI Agent in this workflow.',
            nodeId: n.id,
          });
        }
      }
    }
  }

  return issues;
}

export const REDIS_OPERATIONS = [
  'get',
  'set',
  'delete',
  'increment',
  'list_push',
  'list_pop',
  'list_length',
] as const;
const REDIS_LIST_ENDS = ['left', 'right'];
const REDIS_RESERVED_KEY_PREFIXES = ['foundryx:'];
const REDIS_MAX_KEY_LENGTH = 512;

function isMerge(value: unknown): boolean {
  return typeof value === 'string' && value.includes('{{');
}

/**
 * Publish-time checks on LITERAL Redis config (merge expressions resolve at
 * run time). Mirror of the backend `literal_config_issues` - keep in parity.
 */
export function redisConfigIssues(config: Record<string, unknown>): string[] {
  const issues: string[] = [];
  const op = config.operation;
  if (typeof op !== 'string' || !(REDIS_OPERATIONS as readonly string[]).includes(op)) {
    issues.push('Redis: "Operation" must be one of the supported commands.');
    return issues;
  }
  const key = config.key;
  if (typeof key === 'string' && key.trim() && !isMerge(key)) {
    const trimmed = key.trim();
    if (trimmed.length > REDIS_MAX_KEY_LENGTH) {
      issues.push(`Redis: the key exceeds ${REDIS_MAX_KEY_LENGTH} characters.`);
    } else if (/[\r\n\u0000]/.test(trimmed)) {
      issues.push('Redis: the key contains an invalid character.');
    } else if (
      REDIS_RESERVED_KEY_PREFIXES.some((p) => trimmed.toLowerCase().startsWith(p))
    ) {
      issues.push('Redis: that key prefix is reserved.');
    }
  }
  const end = config.end;
  if (
    (op === 'list_push' || op === 'list_pop') &&
    end !== undefined &&
    end !== null &&
    end !== '' &&
    !REDIS_LIST_ENDS.includes(String(end))
  ) {
    // A missing end defaults to Right at run time; only a wrong value fails.
    issues.push('Redis: "List end" must be Left or Right.');
  }
  const ttl = config.ttlSeconds;
  if (op === 'set' && typeof ttl === 'string' && ttl.trim() && !isMerge(ttl)) {
    if (!/^\d+$/.test(ttl.trim()) || Number(ttl.trim()) < 1) {
      issues.push('Redis: "TTL seconds" must be a positive whole number.');
    }
  }
  const amount = config.amount;
  if (
    op === 'increment' &&
    typeof amount === 'string' &&
    amount.trim() &&
    !isMerge(amount)
  ) {
    if (!/^-?\d+$/.test(amount.trim())) {
      issues.push('Redis: "Amount" must be a whole number.');
    }
  }
  return issues;
}
