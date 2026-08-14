/**
 * Pure helpers over the workflow definition doc (plan sprint-2/08 D3) — the
 * editor-agnostic graph contract. All functions are immutable (return a new
 * doc) so undo/redo can keep a history of snapshots, exactly like the email
 * editor's block-doc helpers.
 */
import { catalogEntry, isTriggerType } from '@/lib/workflow-catalog';
import type {
  WorkflowDefinition,
  WorkflowEdge,
  WorkflowNode,
  WorkflowNodeConfig,
  WorkflowNodeKind,
} from '@/types/workflows';

export const WORKFLOW_SCHEMA_VERSION = 1;

/** Stable short id for nodes/edges (forever-contract ids). */
export function newId(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 8)}`;
}

export function createBlankDefinition(): WorkflowDefinition {
  return { schemaVersion: WORKFLOW_SCHEMA_VERSION, nodes: [], edges: [] };
}

/** Default config for a freshly-dropped node of `type`. */
function defaultConfig(type: string): WorkflowNodeConfig {
  if (type === 'manual') return { inputs: [] };
  if (type === 'email.send') return { mode: 'template' };
  if (type === 'entity.field_changed') return { entityType: '', field: '' };
  if (type === 'entity.status_changed') return { entityType: '', fromStatus: '', toStatus: '' };
  if (type === 'entity.transition_status') return { entityType: '', recordId: '', toStatus: '' };
  if (type === 'entity.update') return { entityType: '', recordId: '', assignments: [] };
  if (type.startsWith('entity.')) return { entityType: '' };
  if (type === 'form.submitted') return { formId: '' };
  if (type === 'schedule.cron') return { cron: '0 9 * * *', timezone: '' };
  if (type === 'if') return { conditions: null };
  // Omnichannel + AI Agent nodes (plan sprint-4/17).
  if (type === 'omnichannel.message_received') return { channelId: null };
  if (type === 'omnichannel.get_contact') return { contactId: '' };
  if (type === 'omnichannel.send_message') return { contactId: '', message: '' };
  if (type === 'ai_agent.run')
    return { agentId: '', instructions: '', inputText: '', outputParams: [] };
  return {};
}

export function createNode(
  type: string,
  position: { x: number; y: number },
): WorkflowNode {
  const entry = catalogEntry(type);
  const kind: WorkflowNodeKind = entry?.kind ?? (isTriggerType(type) ? 'trigger' : 'action');
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

/** A node's display name — the user-set `config.name`, else the catalog label.
 * Names disambiguate two same-type nodes (n8n behavior); refs stay id-based so
 * a rename never breaks an expression. */
export function nodeDisplayName(node: WorkflowNode, fallbackLabel: string): string {
  const name = node.config?.name;
  return typeof name === 'string' && name.trim() ? name.trim() : fallbackLabel;
}

/** A default node name unique within the doc — appends " 2", " 3"… on clash so
 * every node is identifiable in the dynamic-content picker. */
export function uniqueNodeName(doc: WorkflowDefinition, base: string): string {
  const used = new Set(
    doc.nodes.map((n) => nodeDisplayName(n, catalogEntry(n.type)?.label ?? n.type)),
  );
  if (!used.has(base)) return base;
  let i = 2;
  while (used.has(`${base} ${i}`)) i++;
  return `${base} ${i}`;
}

export function addNode(doc: WorkflowDefinition, node: WorkflowNode): WorkflowDefinition {
  return { ...doc, nodes: [...doc.nodes, node] };
}

export function removeNode(doc: WorkflowDefinition, nodeId: string): WorkflowDefinition {
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

/** Swap a node's catalog type in place (quick replace / change trigger) —
 * resets config to the new type's defaults but keeps the node id, position,
 * name and (same-kind) edges. */
export function replaceNodeType(
  doc: WorkflowDefinition,
  nodeId: string,
  newType: string,
): WorkflowDefinition {
  const entry = catalogEntry(newType);
  const kind: WorkflowNodeKind = entry?.kind ?? (isTriggerType(newType) ? 'trigger' : 'action');
  return {
    ...doc,
    nodes: doc.nodes.map((n) =>
      n.id === nodeId
        ? { ...n, type: newType, kind, config: { ...defaultConfig(newType), name: n.config.name } }
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
    nodes: doc.nodes.map((n) => (positions[n.id] ? { ...n, position: positions[n.id] } : n)),
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
  // One outgoing edge per (source, port) for the linear v1 — replace any
  // existing edge on the same port (n8n reconnect behavior).
  const port = edge.sourcePort ?? 'out';
  const kept = doc.edges.filter(
    (e) => !(e.source === edge.source && (e.sourcePort ?? 'out') === port),
  );
  return { ...doc, edges: [...kept, { ...edge, id: newId('e'), sourcePort: port }] };
}

export function removeEdge(doc: WorkflowDefinition, edgeId: string): WorkflowDefinition {
  return { ...doc, edges: doc.edges.filter((e) => e.id !== edgeId) };
}

/** Topological order from the trigger; nodes unreachable from it trail at the
 * end (the publish validator flags those — D17). */
export function topoOrder(doc: WorkflowDefinition): WorkflowNode[] {
  const indegree = new Map<string, number>(doc.nodes.map((n) => [n.id, 0]));
  for (const e of doc.edges) indegree.set(e.target, (indegree.get(e.target) ?? 0) + 1);
  const queue = doc.nodes.filter((n) => (indegree.get(n.id) ?? 0) === 0).map((n) => n.id);
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

/** Mirror of the backend `validate_definition` (D17) — surfaced live in the
 * editor so publish failures are visible before the click. */
export function validateDefinition(doc: WorkflowDefinition): DefinitionIssue[] {
  const issues: DefinitionIssue[] = [];
  const triggers = doc.nodes.filter((n) => n.kind === 'trigger');
  if (triggers.length === 0) issues.push({ level: 'error', message: 'Add a trigger to start the workflow.' });
  if (triggers.length > 1) issues.push({ level: 'error', message: 'A workflow can have only one trigger.' });

  const trigger = triggers[0];
  if (trigger && doc.edges.some((e) => e.target === trigger.id)) {
    issues.push({ level: 'error', message: 'The trigger cannot have an incoming connection.', nodeId: trigger.id });
  }

  // Unique node names — refs are id-based but a duplicate name is ambiguous in
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
        issues.push({ level: 'error', message: `Two nodes are named "${nm}" — names must be unique.`, nodeId: n.id });
        flagged.add(nm);
      }
    }
  }

  // Reachability from the trigger (orphans block — D17).
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
        issues.push({ level: 'error', message: 'Node is not connected to the trigger.', nodeId: n.id });
      }
    }
  }

  // Required config per node (catalog-driven).
  for (const n of doc.nodes) {
    const entry = catalogEntry(n.type);
    if (!entry) continue;
    for (const field of entry.fields) {
      if (field.showWhen && n.config[field.showWhen.field] !== field.showWhen.value) {
        continue; // hidden field — don't require it
      }
      if (field.required) {
        const value = n.config[field.key];
        const empty =
          value === undefined ||
          value === null ||
          value === '' ||
          (Array.isArray(value) && value.length === 0);
        if (empty) {
          issues.push({ level: 'error', message: `${entry.label}: "${field.label}" is required.`, nodeId: n.id });
        }
      }
    }
    // Connection-resolvability warning (warn-not-block, D17) needs real
    // connection data — added in Phase B.
  }

  return issues;
}
