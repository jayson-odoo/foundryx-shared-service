'use client';

/**
 * Run replay (plan sprint-2/08 D16) - the RIGHT pane of the Logs two-pane.
 * Read-only canvas of the run's pinned-version graph, each node tinted by its
 * execution status; click a node to inspect its input/output/error.
 * "Debug in editor" (with confirm) hands the run's graph + data to the Editor
 * tab, where the fix persists for future runs.
 */
import { useMemo, useState } from 'react';
import { MarkerType, type Edge, type Node } from '@xyflow/react';
import { Bug, Check, Copy } from 'lucide-react';
import type { WorkflowRunDetail } from '@/types/workflows';
import { catalogEntry } from '@/lib/workflow-catalog';
import { ClampedText } from '@/components/platform/clamped-text';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { cn } from '@/lib/utils';
import { FlowCanvas } from '@/components/platform/flow-canvas';
import {
  WorkflowFlowNode,
  type WorkflowNodeData,
} from '@/components/platform/workflow-canvas';
import { NodeRunStatusBadge, RunStatusBadge } from './run-status-badge';

const NODE_TYPES = { workflow: WorkflowFlowNode };

export interface RunReplayProps {
  run: WorkflowRunDetail;
  onDebugInEditor: (runId: string) => void;
}

export function RunReplay({ run, onDebugInEditor }: RunReplayProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const cache = useMemo(
    () => Object.fromEntries(run.nodes.map((n) => [n.nodeId, n])),
    [run],
  );

  const nodes = useMemo<Node[]>(
    () =>
      run.definition.nodes.map((node) => ({
        id: node.id,
        type: 'workflow',
        position: node.position,
        data: {
          node,
          catalog: catalogEntry(node.type),
          runStatus: cache[node.id]?.status,
        } satisfies WorkflowNodeData,
        deletable: false,
        selected: node.id === selectedNodeId,
      })),
    [run, cache, selectedNodeId],
  );

  const edges = useMemo<Edge[]>(
    () =>
      run.definition.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.sourcePort ?? 'out',
        type: 'smoothstep',
        markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
        style: { strokeWidth: 1.5 },
      })),
    [run],
  );

  const selectedNode =
    run.definition.nodes.find((n) => n.id === selectedNodeId) ?? null;
  const selectedData = selectedNodeId ? cache[selectedNodeId] : null;

  return (
    <div className="flex flex-col gap-3" data-testid="run-replay">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <RunStatusBadge status={run.status} />
          <span className="text-xs text-muted-foreground">
            {run.versionNumber > 0 ? `v${run.versionNumber}` : 'draft'} ·{' '}
            {run.triggeredBy}
            {run.isTest ? ' · test' : ''}
          </span>
          {run.correlationKey && (
            <span
              className="max-w-full rounded-md bg-muted px-1.5 py-0.5 font-mono text-2xs text-muted-foreground sm:max-w-[16rem]"
              data-testid="run-correlation-key"
            >
              <ClampedText text={run.correlationKey} lines={1} />
            </span>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setConfirmOpen(true)}
          data-testid="debug-in-editor"
        >
          <Bug className="size-3.5" /> Debug in editor
        </Button>
      </div>

      {run.error && (
        <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {run.error}
        </p>
      )}

      <div className="flex flex-col items-stretch gap-3 lg:flex-row lg:items-start">
        <div className="min-w-0 flex-1">
          <FlowCanvas
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            className="h-[50vh] min-h-72 lg:h-[calc(100vh-23rem)] lg:min-h-[420px]"
            readOnly
            onNodeClick={(id) => setSelectedNodeId(id)}
            onPaneClick={() => setSelectedNodeId(null)}
          />
        </div>

        <aside className="w-full shrink-0 rounded-lg border border-input bg-background p-3 lg:w-72">
          {!selectedNode ? (
            <p className="px-1 py-8 text-center text-xs text-muted-foreground">
              Select a node to inspect its data.
            </p>
          ) : (
            <div className="flex flex-col gap-3" data-testid="node-inspector">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-foreground">
                  {catalogEntry(selectedNode.type)?.label ?? selectedNode.type}
                </span>
                {selectedData && (
                  <NodeRunStatusBadge status={selectedData.status} />
                )}
              </div>
              {resolvedInput(selectedData?.inputJson) && (
                <DataBlock
                  label="Resolved input"
                  value={resolvedInput(selectedData?.inputJson)}
                />
              )}
              <DataBlock label="Input" value={selectedData?.inputJson} />
              <DataBlock label="Output" value={selectedData?.outputJson} />
              {selectedData?.error && (
                <ErrorBlock error={selectedData.error} />
              )}
            </div>
          )}
        </aside>
      </div>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent className="md:max-w-[420px]">
          <AlertDialogHeader>
            <AlertDialogTitle>Debug this run in the editor?</AlertDialogTitle>
            <AlertDialogDescription>
              The editor opens with this run’s data pinned onto your current
              draft, so you can fix the flow and re-run nodes. Your draft is
              kept - nothing is replaced.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => onDebugInEditor(run.id)}
              data-testid="confirm-debug"
            >
              Load into editor
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

interface DataBlockProps {
  label: string;
  value: unknown;
}

function DataBlock({ label, value }: DataBlockProps) {
  const [copied, setCopied] = useState(false);

  const textToCopy = value == null ? '' : JSON.stringify(value, null, 2);

  const handleCopy = async () => {
    if (!textToCopy || typeof navigator === 'undefined' || !navigator.clipboard) {
      return;
    }

    try {
      await navigator.clipboard.writeText(textToCopy);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Silently fail if clipboard write is not allowed
    }
  };

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
        {value != null && (
          <button
            type="button"
            onClick={handleCopy}
            aria-label={`Copy ${label}`}
            className={cn(PRESSED_CLASS, 'hover:text-foreground text-muted-foreground transition-colors')}
          >
            {copied ? (
              <Check className="size-3.5" />
            ) : (
              <Copy className="size-3.5" />
            )}
          </button>
        )}
      </div>
      <pre className="max-h-40 overflow-auto rounded-md bg-muted p-2 text-2xs text-foreground">
        {value == null ? '-' : textToCopy}
      </pre>
    </div>
  );
}

interface ErrorBlockProps {
  error: string;
}

function ErrorBlock({ error }: ErrorBlockProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (typeof navigator === 'undefined' || !navigator.clipboard) {
      return;
    }

    try {
      await navigator.clipboard.writeText(error);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Silently fail if clipboard write is not allowed
    }
  };

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">
          Error
        </span>
        <button
          type="button"
          onClick={handleCopy}
          aria-label="Copy Error"
          className={cn(PRESSED_CLASS, 'hover:text-destructive text-muted-foreground transition-colors')}
        >
          {copied ? (
            <Check className="size-3.5" />
          ) : (
            <Copy className="size-3.5" />
          )}
        </button>
      </div>
      <pre className="overflow-auto rounded-md bg-destructive/10 p-2 text-2xs text-destructive">
        {error}
      </pre>
    </div>
  );
}


/**
 * The rendered field values a node actually used (executor `_node_input_json`
 * `resolved`, and a Code node's `runtime.input`) - shown so Logs display what
 * was SENT, not just the template (plan sprint-4/19 user request).
 */
function resolvedInput(inputJson: unknown): Record<string, unknown> | null {
  if (!inputJson || typeof inputJson !== 'object') return null;
  const obj = inputJson as Record<string, unknown>;
  if (obj.resolved && typeof obj.resolved === 'object') {
    return obj.resolved as Record<string, unknown>;
  }
  const runtime = obj.runtime as Record<string, unknown> | undefined;
  if (runtime && runtime.input && typeof runtime.input === 'object') {
    return runtime.input as Record<string, unknown>;
  }
  return null;
}
