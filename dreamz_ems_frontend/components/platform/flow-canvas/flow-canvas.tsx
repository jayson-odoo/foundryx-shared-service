'use client';

/**
 * Generic node-graph canvas (sprint-2/01 D10) — a thin, reusable wrapper over
 * @xyflow/react. Built engine-agnostic on purpose: the Status engine renders
 * statuses/transitions through it today, the Workflow engine (BL-025) reuses
 * it for workflow nodes later. No status-specific logic in here.
 *
 * Supports CONTROLLED usage (pass onNodesChange/onEdgesChange for smooth,
 * locally-applied dragging) and uncontrolled static rendering.
 */
import { useMemo } from 'react';
import {
  Background,
  Controls,
  type Connection,
  type Edge,
  type EdgeChange,
  type EdgeTypes,
  type Node,
  type NodeChange,
  type NodeTypes,
  ReactFlow,
  type ReactFlowInstance,
  type ReactFlowProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { cn } from '@/lib/utils';

export interface FlowCanvasProps {
  nodes: Node[];
  edges: Edge[];
  nodeTypes?: NodeTypes;
  edgeTypes?: EdgeTypes;
  /** Controlled-mode change handlers (drag/select apply locally = smooth). */
  onNodesChange?: (changes: NodeChange[]) => void;
  onEdgesChange?: (changes: EdgeChange[]) => void;
  /** Drag-create an edge between two nodes (omit = connecting disabled). */
  onConnect?: (connection: Connection) => void;
  onNodeClick?: (nodeId: string) => void;
  /** Right-click a node — gives the cursor position for a context menu. */
  onNodeContextMenu?: (nodeId: string, x: number, y: number) => void;
  onEdgeClick?: (edgeId: string) => void;
  onNodeDragStop?: (nodeId: string, x: number, y: number) => void;
  onPaneClick?: () => void;
  /** Delete-key handling for deletable elements (edges in the status engine). */
  onEdgesDelete?: (edges: Edge[]) => void;
  /** Surfaces the React Flow instance (fitView after auto-layout etc.). */
  onInit?: (instance: ReactFlowInstance) => void;
  readOnly?: boolean;
  className?: string;
}

export function FlowCanvas({
  nodes,
  edges,
  nodeTypes,
  edgeTypes,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onNodeClick,
  onNodeContextMenu,
  onEdgeClick,
  onNodeDragStop,
  onPaneClick,
  onEdgesDelete,
  onInit,
  readOnly = false,
  className,
}: FlowCanvasProps) {
  const interactionProps = useMemo<Partial<ReactFlowProps>>(
    () =>
      readOnly
        ? {
            nodesDraggable: false,
            nodesConnectable: false,
            elementsSelectable: true, // selecting to inspect is still fine
          }
        : {
            nodesDraggable: true,
            nodesConnectable: Boolean(onConnect),
            elementsSelectable: true,
          },
    [readOnly, onConnect],
  );

  return (
    <div className={cn('h-[560px] w-full rounded-xl border border-border bg-background', className)} data-testid="flow-canvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={readOnly ? undefined : onConnect}
        onNodeClick={onNodeClick ? (_, node) => onNodeClick(node.id) : undefined}
        onNodeContextMenu={
          onNodeContextMenu
            ? (event, node) => {
                event.preventDefault();
                onNodeContextMenu(node.id, event.clientX, event.clientY);
              }
            : undefined
        }
        onEdgeClick={onEdgeClick ? (_, edge) => onEdgeClick(edge.id) : undefined}
        onNodeDragStop={
          onNodeDragStop
            ? (_, node) => onNodeDragStop(node.id, node.position.x, node.position.y)
            : undefined
        }
        onPaneClick={onPaneClick}
        onEdgesDelete={readOnly ? undefined : onEdgesDelete}
        onInit={onInit}
        fitView
        proOptions={{ hideAttribution: true }}
        // Delete/Backspace removes selected DELETABLE elements; nodes are
        // marked non-deletable by callers (nodes delete via their drawer).
        deleteKeyCode={readOnly || !onEdgesDelete ? null : ['Delete', 'Backspace']}
        {...interactionProps}
      >
        <Background gap={16} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
