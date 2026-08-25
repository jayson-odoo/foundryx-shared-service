'use client';

/**
 * Typed workflow node for the React Flow canvas (plan sprint-2/08 D15). Unlike
 * the status node (simple labeled box, bidirectional), a workflow node is
 * directed: a target handle on top (except triggers) and source handle(s) on
 * the bottom. IF nodes (slice 09) render two labeled source ports.
 *
 * In the read-only run replay the node is tinted by its execution status (D16).
 */
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Zap } from 'lucide-react';
import { cn } from '@/lib/utils';
import { describeCron } from '@/lib/cron';
import { nodeDisplayName } from '@/lib/workflow-doc';
import type { NodeCatalogEntry, WorkflowNode, WorkflowNodeRunStatus } from '@/types/workflows';
import { WORKFLOW_NODE_ICONS } from './workflow-icons';

const ICONS = WORKFLOW_NODE_ICONS;

export interface WorkflowNodeData {
  node: WorkflowNode;
  catalog?: NodeCatalogEntry;
  /** Run-replay tint (D16) - omitted in the editor. */
  runStatus?: WorkflowNodeRunStatus;
  [key: string]: unknown;
}

const RUN_RING: Record<WorkflowNodeRunStatus, string> = {
  success: 'ring-2 ring-green-500',
  failed: 'ring-2 ring-destructive',
  running: 'ring-2 ring-amber-500 animate-pulse',
  skipped: 'ring-1 ring-muted-foreground/40 opacity-60',
  pending: 'ring-1 ring-muted-foreground/30',
};

export function WorkflowFlowNode({ data, selected }: NodeProps & { data: WorkflowNodeData }) {
  const { node, catalog, runStatus } = data;
  const Icon = ICONS[catalog?.icon ?? ''] ?? Zap;
  const isTrigger = node.kind === 'trigger';
  const isIf = node.kind === 'if';
  const typeLabel = catalog?.label ?? node.type;
  const label = nodeDisplayName(node, typeLabel);
  const baseSummary = nodeSummary(node);
  // When the node carries a CUSTOM name (≠ its type label), surface the actual
  // type in the subtitle so a name like "Record created" can never masquerade
  // as a different trigger type (foolproof-UI - the card states what it IS).
  const summary =
    label !== typeLabel
      ? [typeLabel, baseSummary].filter(Boolean).join(' · ')
      : baseSummary;

  return (
    <div
      data-testid={`workflow-node-${node.id}`}
      data-node-type={node.type}
      className={cn(
        'min-w-52 rounded-xl border bg-card px-3.5 py-3 shadow-sm transition-colors',
        selected ? 'border-primary ring-1 ring-primary' : 'border-border',
        runStatus && RUN_RING[runStatus],
      )}
    >
      {!isTrigger && (
        <Handle
          type="target"
          position={Position.Top}
          data-testid="target-handle"
          className="!size-2.5 !bg-muted-foreground"
        />
      )}
      <div className="flex items-center gap-2.5">
        <span
          className={cn(
            'flex size-8 shrink-0 items-center justify-center rounded-lg',
            isTrigger ? 'bg-primary/10 text-primary' : isIf ? 'bg-amber-500/10 text-amber-600' : 'bg-muted text-foreground',
          )}
        >
          <Icon className="size-4" />
        </span>
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              {isTrigger ? 'Trigger' : isIf ? 'Condition' : 'Action'}
            </span>
          </div>
          <div className="truncate text-sm font-medium text-foreground">{label}</div>
          {summary && <div className="truncate text-xs text-muted-foreground">{summary}</div>}
        </div>
      </div>

      {isIf ? (
        <>
          <Handle id="true" type="source" data-testid="source-handle-true" position={Position.Bottom} style={{ left: '30%' }} className="!size-2.5 !bg-green-500" />
          <Handle id="false" type="source" data-testid="source-handle-false" position={Position.Bottom} style={{ left: '70%' }} className="!size-2.5 !bg-destructive" />
        </>
      ) : (
        <Handle id="out" type="source" position={Position.Bottom} data-testid="source-handle" className="!size-2.5 !bg-primary" />
      )}
    </div>
  );
}

/** A one-line gist of the node's config for the card. */
function nodeSummary(node: WorkflowNode): string {
  const str = (k: string): string => {
    const v = node.config[k];
    return typeof v === 'string' ? v : '';
  };
  switch (node.type) {
    case 'email.send':
      return str('to') ? `to ${str('to')}` : 'no recipient set';
    case 'manual': {
      const inputs = node.config.inputs;
      const count = Array.isArray(inputs) ? inputs.length : 0;
      return count ? `${count} input${count === 1 ? '' : 's'}` : 'no inputs';
    }
    case 'schedule.cron':
      return str('cron') ? describeCron(str('cron')) : 'no schedule';
    case 'entity.field_changed':
      return str('entityType') ? `${str('entityType')} · ${str('field') || 'field'}` : 'pick an entity';
    case 'entity.status_changed':
      return str('entityType') ? `${str('entityType')} status` : 'pick an entity';
    case 'entity.transition_status':
      return str('entityType') ? `${str('entityType')} → ${str('toStatus') || 'status'}` : 'pick an entity';
    case 'entity.update': {
      const a = node.config.assignments;
      const count = Array.isArray(a) ? a.length : 0;
      return str('entityType') ? `${str('entityType')} · ${count} field${count === 1 ? '' : 's'}` : 'pick an entity';
    }
    case 'storage.put':
    case 'storage.get':
    case 'storage.delete':
      return str('key') || 'no key set';
    case 'if':
      return node.config.conditions ? 'conditional' : 'always true';
    default:
      return node.type.startsWith('entity.') ? str('entityType') || 'pick an entity' : '';
  }
}
