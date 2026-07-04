'use client';

/**
 * Status node for the flow canvas (sprint-2/01). Shows the status color,
 * label and trait-flag badges. A TERMINAL status renders no source handle —
 * outgoing edges are impossible at the UI layer too (strict graph, D4).
 */
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Badge } from '@/components/ui/badge';
import { colorToHex } from '@/components/platform/status-badge';
import { cn } from '@/lib/utils';
import type { StatusNodeData } from '@/types/status-engine';

export interface StatusFlowNodeProps extends NodeProps {
  data: { status: StatusNodeData };
}

export function StatusFlowNode({ data, selected }: StatusFlowNodeProps) {
  const status = data.status;
  return (
    <div
      data-testid={`status-node-${status.key}`}
      className={cn(
        'min-w-40 rounded-lg border bg-card px-3.5 py-2.5 shadow-xs transition-colors',
        selected ? 'border-primary ring-1 ring-primary' : 'border-border',
        !status.isActive && 'opacity-50',
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        data-testid="target-handle"
        className="!size-2.5 !bg-muted-foreground"
      />
      <div className="flex items-center gap-2">
        <span
          className="size-2.5 shrink-0 rounded-full"
          style={{ backgroundColor: colorToHex(status.color) }}
        />
        <span className="text-sm font-medium text-foreground">{status.label}</span>
      </div>
      {(status.isInitial ||
        status.isTerminal ||
        status.isDefault ||
        status.blocksAccess ||
        status.isArchived ||
        !status.isActive) && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {status.isInitial && (
            <Badge variant="info" appearance="light" size="sm">
              Initial
            </Badge>
          )}
          {status.isDefault && (
            <Badge variant="primary" appearance="light" size="sm">
              Default
            </Badge>
          )}
          {status.isTerminal && (
            <Badge variant="secondary" appearance="light" size="sm">
              Terminal
            </Badge>
          )}
          {status.blocksAccess && (
            <Badge variant="warning" appearance="light" size="sm">
              Blocks access
            </Badge>
          )}
          {status.isArchived && (
            <Badge variant="secondary" appearance="light" size="sm">
              Archived
            </Badge>
          )}
          {!status.isActive && (
            <Badge variant="destructive" appearance="light" size="sm">
              Inactive
            </Badge>
          )}
        </div>
      )}
      {!status.isTerminal && (
        <Handle
          type="source"
          position={Position.Right}
          data-testid="source-handle"
          className="!size-2.5 !bg-primary"
        />
      )}
    </div>
  );
}
