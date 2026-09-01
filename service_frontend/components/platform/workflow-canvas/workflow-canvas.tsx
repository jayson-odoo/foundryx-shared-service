'use client';

/**
 * Workflow editor canvas (plan sprint-2/08 D15) - a directed, ported node graph
 * over the shared FlowCanvas (@xyflow/react) primitives. Palette (left,
 * dnd-kit + click-to-add) → canvas (center) → node config drawer (right).
 * Client-side undo/redo + non-destructive Tidy (BL-064) over the definition doc.
 *
 * The definition doc is the single source of truth (controlled by the parent);
 * React Flow node/edge state is local for smooth dragging and re-derived when
 * the doc changes structurally.
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  DndContext,
  PointerSensor,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  applyEdgeChanges,
  applyNodeChanges,
  MarkerType,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type ReactFlowInstance,
} from '@xyflow/react';
import {
  ChevronLeft,
  ChevronRight,
  Redo2,
  RefreshCw,
  Search,
  Trash2,
  TriangleAlert,
  Undo2,
  Wand2,
} from 'lucide-react';
import { toast } from 'sonner';
import type {
  WorkflowDefinition,
  WorkflowMetadata,
  WorkflowNodeConfig,
  WorkflowRunNode,
} from '@/types/workflows';
import {
  ACTION_CATALOG,
  catalogEntry,
  TRIGGER_CATALOG,
} from '@/lib/workflow-catalog';
import {
  addEdge as addDocEdge,
  addNode as addDocNode,
  createNode,
  hasTrigger,
  moveNode,
  removeEdges as removeDocEdges,
  removeNode as removeDocNode,
  replaceNodeType,
  setPositions,
  uniqueNodeName,
  updateNodeConfig,
  validateDefinition,
  wouldCreateCycle,
} from '@/lib/workflow-doc';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  FlowCanvas,
  layoutGraph,
  useHistory,
} from '@/components/platform/flow-canvas';
import { NodeConfigDrawer, type TemplateOption } from './node-config-drawer';
import { NodePalette } from './node-palette';
import { WorkflowFlowNode, type WorkflowNodeData } from './workflow-node';

const NODE_TYPES = { workflow: WorkflowFlowNode };

/** Debug session loaded from a past run (Logs → Debug in editor). */
export interface WorkflowDebugBundle {
  /** Cached per-node outputs from the run (+ updates as nodes re-execute). */
  data: Record<string, WorkflowRunNode>;
  busy: boolean;
  onExecuteNode: (nodeId: string) => void;
}

export interface WorkflowCanvasProps {
  doc: WorkflowDefinition;
  onChange: (doc: WorkflowDefinition) => void;
  editing: boolean;
  templateOptions: TemplateOption[];
  /** Triggerable entities + statuses/fields the node drawers resolve (D6). */
  metadata: WorkflowMetadata;
  canCode?: boolean;
  debug?: WorkflowDebugBundle | null;
}

/** Branch-port edge styling - green true / red false (D8 IF node). */
const BRANCH_EDGE: Record<string, { label: string; stroke: string }> = {
  true: { label: 'True', stroke: '#16a34a' },
  false: { label: 'False', stroke: '#dc2626' },
};

function CanvasDropZone({ children }: { children: React.ReactNode }) {
  const { setNodeRef } = useDroppable({ id: 'workflow-canvas-drop' });
  return (
    <div ref={setNodeRef} className="relative w-full min-w-0 flex-1">
      {children}
    </div>
  );
}

export function WorkflowCanvas({
  doc,
  onChange,
  editing,
  templateOptions,
  metadata,
  debug,
  canCode = true,
}: WorkflowCanvasProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    nodeId: string;
  } | null>(null);
  const [menuView, setMenuView] = useState<'main' | 'replace'>('main');
  const [replaceQuery, setReplaceQuery] = useState('');
  const menuRef = useRef<HTMLDivElement>(null);
  const [menuCoords, setMenuCoords] = useState<{
    left: number;
    top: number;
  } | null>(null);

  // Clamp the context menu into the viewport (flips up/left near an edge so the
  // popup never truncates - measured before paint, no flicker).
  useLayoutEffect(() => {
    if (!contextMenu || !menuRef.current) {
      setMenuCoords(null);
      return;
    }
    const rect = menuRef.current.getBoundingClientRect();
    const pad = 8;
    let left = contextMenu.x;
    let top = contextMenu.y;
    if (left + rect.width > window.innerWidth - pad)
      left = window.innerWidth - rect.width - pad;
    if (top + rect.height > window.innerHeight - pad)
      top = window.innerHeight - rect.height - pad;
    setMenuCoords({ left: Math.max(pad, left), top: Math.max(pad, top) });
  }, [contextMenu, menuView]);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [flowInstance, setFlowInstance] = useState<ReactFlowInstance | null>(
    null,
  );

  // ---- undo/redo over the whole draft doc (shared hook, closes BL-064) ----
  const { set: emit, undo, redo, canUndo, canRedo } = useHistory(doc, onChange);

  useEffect(() => {
    if (!editing) return;
    const handler = (e: KeyboardEvent) => {
      const isUndoRedo =
        (e.metaKey || e.ctrlKey) &&
        (e.key.toLowerCase() === 'z' || e.key.toLowerCase() === 'y');
      if (!isUndoRedo) return;
      const target = e.target as HTMLElement | null;
      if (target?.closest('input, textarea, [contenteditable="true"]')) return;
      e.preventDefault();
      if (e.key.toLowerCase() === 'y' || e.shiftKey) redo();
      else undo();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [editing, undo, redo]);

  // Escape closes the context menu.
  useEffect(() => {
    if (!contextMenu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setContextMenu(null);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [contextMenu]);

  // Delete/Backspace removes the selected node (not while typing in a field).
  useEffect(() => {
    if (!editing) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key !== 'Delete' && e.key !== 'Backspace') return;
      const target = e.target as HTMLElement | null;
      // Skip while focus is on any interactive control - SearchSelect/dropdown
      // triggers are buttons/comboboxes (not inputs), so a reflexive Backspace
      // after a selection would otherwise delete the whole node mid-config.
      if (
        target?.closest(
          'input, textarea, [contenteditable="true"], button, a, select, [role="combobox"], [role="listbox"], [role="menu"], [role="dialog"]',
        )
      )
        return;
      if (!selectedNodeId) return;
      e.preventDefault();
      emit(removeDocNode(doc, selectedNodeId));
      setSelectedNodeId(null);
      setContextMenu(null);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [editing, selectedNodeId, doc, emit]);

  // ---- derive RF state from the doc (structural changes only) ----
  useEffect(() => {
    setNodes(
      doc.nodes.map((node) => ({
        id: node.id,
        type: 'workflow',
        position: node.position,
        data: {
          node,
          catalog: catalogEntry(node.type),
          runStatus: debug?.data[node.id]?.status,
        } satisfies WorkflowNodeData,
        deletable: false, // nodes delete via the drawer
        selected: node.id === selectedNodeId,
      })),
    );
    setEdges(
      doc.edges.map((edge) => {
        const branch = BRANCH_EDGE[edge.sourcePort ?? ''];
        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          sourceHandle: edge.sourcePort ?? 'out',
          type: 'smoothstep',
          label: branch?.label,
          labelStyle: branch
            ? { fill: branch.stroke, fontSize: 11, fontWeight: 600 }
            : undefined,
          labelBgStyle: branch ? { fill: 'var(--background)' } : undefined,
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 18,
            height: 18,
            color: branch?.stroke,
          },
          style: { strokeWidth: 1.5, stroke: branch?.stroke },
          deletable: true,
        };
      }),
    );
    // selectedNodeId intentionally excluded - selection re-tint handled below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc]);

  // Re-tint selection without rebuilding the whole graph.
  useEffect(() => {
    setNodes((current) =>
      current.map((n) => ({ ...n, selected: n.id === selectedNodeId })),
    );
  }, [selectedNodeId]);

  // Re-tint by debug run status as nodes (re-)execute, without a full rebuild.
  useEffect(() => {
    setNodes((current) =>
      current.map((n) => ({
        ...n,
        data: {
          ...(n.data as WorkflowNodeData),
          runStatus: debug?.data[n.id]?.status,
        },
      })),
    );
  }, [debug]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) =>
      setNodes((current) => applyNodeChanges(changes, current)),
    [],
  );
  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) =>
      setEdges((current) => applyEdgeChanges(changes, current)),
    [],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!editing || !connection.source || !connection.target) return;
      if (wouldCreateCycle(doc, connection.source, connection.target)) {
        toast.error('That connection would create a loop.');
        return;
      }
      emit(
        addDocEdge(doc, {
          source: connection.source,
          target: connection.target,
          sourcePort: connection.sourceHandle ?? 'out',
        }),
      );
    },
    [doc, editing, emit],
  );

  const addNodeAt = useCallback(
    (type: string, position?: { x: number; y: number }) => {
      const entry = catalogEntry(type);
      if (
        !canCode &&
        entry &&
        'permission' in entry &&
        entry.permission === 'workflows.code'
      )
        return;
      if (entry?.kind === 'trigger' && hasTrigger(doc)) {
        toast.error('A workflow can have only one trigger.');
        return;
      }
      const pos =
        position ??
        (() => {
          if (!doc.nodes.length) return { x: 80, y: 40 };
          const maxY = Math.max(...doc.nodes.map((n) => n.position.y));
          const anchor = doc.nodes.find((n) => n.position.y === maxY);
          return { x: anchor?.position.x ?? 80, y: maxY + 170 };
        })();
      const created = createNode(type, pos);
      // Seed a unique display name (n8n) so two same-type nodes are tellable
      // apart in the dynamic-content picker.
      const name = uniqueNodeName(doc, entry?.label ?? type);
      const node = { ...created, config: { ...created.config, name } };
      // No auto-connect - the node drops unwired so the author chooses which
      // edge/branch it belongs to (auto-deriving forced wrong edges, esp. on
      // IF false-branches; user feedback).
      emit(addDocNode(doc, node));
      setSelectedNodeId(node.id);
    },
    [canCode, doc, emit],
  );

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );

  const onDragEnd = useCallback(
    (event: DragEndEvent) => {
      if (event.over?.id !== 'workflow-canvas-drop') return;
      const data = event.active.data.current as
        | { source: 'palette'; nodeType: string }
        | undefined;
      if (data?.source !== 'palette') return;
      // Final dragged-item rect (viewport coords) → flow position.
      const rect = event.active.rect.current.translated;
      let position: { x: number; y: number } | undefined;
      if (rect && flowInstance) {
        position = flowInstance.screenToFlowPosition({
          x: rect.left,
          y: rect.top,
        });
      }
      addNodeAt(data.nodeType, position);
    },
    [addNodeAt, flowInstance],
  );

  const tidy = useCallback(() => {
    const arranged = layoutGraph(nodes, edges, { direction: 'TB' });
    const positions = Object.fromEntries(
      arranged.map((n) => [n.id, n.position]),
    );
    // Goes through emit → undoable (BL-064: Tidy never silently nukes a layout).
    emit(setPositions(doc, positions));
    requestAnimationFrame(() =>
      flowInstance?.fitView({ padding: 0.2, duration: 300 }),
    );
  }, [nodes, edges, doc, emit, flowInstance]);

  const selectedNode = useMemo(
    () => doc.nodes.find((n) => n.id === selectedNodeId) ?? null,
    [doc, selectedNodeId],
  );

  const issues = useMemo(
    () => validateDefinition(doc, metadata),
    [doc, metadata],
  );
  const errors = issues.filter((i) => i.level === 'error');

  const handleConfigChange = useCallback(
    (nodeId: string, patch: WorkflowNodeConfig) =>
      emit(updateNodeConfig(doc, nodeId, patch)),
    [doc, emit],
  );

  const handleDelete = useCallback(
    (nodeId: string) => {
      emit(removeDocNode(doc, nodeId));
      setSelectedNodeId(null);
    },
    [doc, emit],
  );

  const handleReplace = useCallback(
    (nodeId: string, newType: string) => {
      const entry = catalogEntry(newType);
      if (
        !canCode &&
        entry &&
        'permission' in entry &&
        entry.permission === 'workflows.code'
      )
        return;
      emit(replaceNodeType(doc, nodeId, newType));
    },
    [canCode, doc, emit],
  );

  const handleNodeContextMenu = useCallback(
    (nodeId: string, x: number, y: number) => {
      if (!editing) return;
      setSelectedNodeId(nodeId);
      setMenuView('main');
      setReplaceQuery('');
      setContextMenu({ x, y, nodeId });
    },
    [editing],
  );

  const contextNode = useMemo(
    () =>
      contextMenu
        ? (doc.nodes.find((n) => n.id === contextMenu.nodeId) ?? null)
        : null,
    [contextMenu, doc],
  );
  const contextReplaceOptions = (
    contextNode?.kind === 'trigger'
      ? TRIGGER_CATALOG
      : contextNode?.kind === 'action'
        ? ACTION_CATALOG
        : []
  ).filter(
    (entry) =>
      canCode ||
      !('permission' in entry) ||
      entry.permission !== 'workflows.code',
  );

  return (
    <DndContext sensors={sensors} onDragEnd={onDragEnd}>
      <div className="flex flex-col gap-2" data-testid="workflow-canvas">
        {editing && errors.length > 0 && (
          <Alert
            variant="warning"
            appearance="light"
            data-testid="canvas-issues"
          >
            <AlertIcon>
              <TriangleAlert />
            </AlertIcon>
            <AlertTitle>
              {errors.length} issue{errors.length === 1 ? '' : 's'} to fix
              before publishing: {errors[0].message}
            </AlertTitle>
          </Alert>
        )}
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
          <aside className="w-full shrink-0 overflow-y-auto rounded-lg border border-input bg-background p-3 lg:h-[calc(100vh-19rem)] lg:min-h-[480px] lg:w-56">
            {editing ? (
              <NodePalette
                hasTrigger={hasTrigger(doc)}
                disabled={!editing}
                canCode={canCode}
                onAdd={(t) => addNodeAt(t)}
              />
            ) : (
              <p className="px-1 py-6 text-center text-xs text-muted-foreground">
                Read-only workflow.
              </p>
            )}
          </aside>

          <CanvasDropZone>
            {editing && (
              <div className="absolute right-2 top-2 z-30 flex items-center gap-1 rounded-md border border-input bg-background p-0.5 shadow-sm">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-7"
                  aria-label="Undo"
                  title="Undo (⌘Z)"
                  data-testid="canvas-undo"
                  disabled={!canUndo}
                  onClick={undo}
                >
                  <Undo2 className="size-4" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-7"
                  aria-label="Redo"
                  title="Redo (⇧⌘Z)"
                  data-testid="canvas-redo"
                  disabled={!canRedo}
                  onClick={redo}
                >
                  <Redo2 className="size-4" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7"
                  data-testid="canvas-tidy"
                  onClick={tidy}
                >
                  <Wand2 className="size-3.5" /> Tidy
                </Button>
              </div>
            )}

            <FlowCanvas
              nodes={nodes}
              edges={edges}
              nodeTypes={NODE_TYPES}
              className="h-[calc(100vh-19rem)] min-h-[480px]"
              readOnly={!editing}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={editing ? onConnect : undefined}
              onNodeClick={(id) => setSelectedNodeId(id)}
              onNodeContextMenu={handleNodeContextMenu}
              onPaneClick={() => {
                setSelectedNodeId(null);
                setContextMenu(null);
              }}
              onNodeDragStop={(id, x, y) => {
                if (!editing) return;
                emit(moveNode(doc, id, { x, y }));
              }}
              onInit={setFlowInstance}
              onEdgesDelete={
                editing
                  ? (deleted) =>
                      emit(
                        removeDocEdges(
                          doc,
                          deleted.map((e) => e.id),
                        ),
                      )
                  : undefined
              }
            />
          </CanvasDropZone>

          <aside className="w-full shrink-0 overflow-y-auto rounded-lg border border-input bg-background p-3 lg:h-[calc(100vh-19rem)] lg:min-h-[480px] lg:w-80">
            <NodeConfigDrawer
              node={selectedNode}
              doc={doc}
              editing={editing}
              templateOptions={templateOptions}
              metadata={metadata}
              onConfigChange={handleConfigChange}
              onDelete={handleDelete}
              onReplaceNode={handleReplace}
              canCode={canCode}
              runData={
                selectedNode && debug
                  ? (debug.data[selectedNode.id] ?? null)
                  : null
              }
              onExecuteNode={
                debug
                  ? () => selectedNode && debug.onExecuteNode(selectedNode.id)
                  : undefined
              }
              executeBusy={debug?.busy}
            />
          </aside>
        </div>
      </div>

      {contextMenu && contextNode && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setContextMenu(null)}
            onContextMenu={(e) => {
              e.preventDefault();
              setContextMenu(null);
            }}
          />
          <div
            ref={menuRef}
            className="fixed z-50 w-56 overflow-hidden rounded-md border border-border bg-popover py-1 shadow-md"
            style={{
              left: menuCoords?.left ?? contextMenu.x,
              top: menuCoords?.top ?? contextMenu.y,
            }}
            data-testid="node-context-menu"
          >
            {menuView === 'main' ? (
              <>
                {contextReplaceOptions.length > 0 && (
                  <>
                    <button
                      type="button"
                      data-testid="context-replace"
                      className="flex w-full items-center justify-between px-2.5 py-1.5 text-left text-sm hover:bg-accent"
                      onClick={() => setMenuView('replace')}
                    >
                      <span className="flex items-center gap-2">
                        <RefreshCw className="size-3.5" /> Replace node
                      </span>
                      <ChevronRight className="size-3.5 text-muted-foreground" />
                    </button>
                    <div className="my-1 h-px bg-border" />
                  </>
                )}
                <button
                  type="button"
                  data-testid="context-delete"
                  className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-sm text-destructive hover:bg-accent"
                  onClick={() => {
                    handleDelete(contextNode.id);
                    setContextMenu(null);
                  }}
                >
                  <Trash2 className="size-3.5" /> Delete node
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left text-xs font-semibold text-muted-foreground hover:bg-accent"
                  onClick={() => setMenuView('main')}
                >
                  <ChevronLeft className="size-3.5" /> Replace with
                </button>
                <div className="relative px-1.5 pb-1.5">
                  <Search className="pointer-events-none absolute left-3.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    autoFocus
                    value={replaceQuery}
                    onChange={(e) => setReplaceQuery(e.target.value)}
                    placeholder="Search types…"
                    aria-label="Search node types"
                    className="h-8 ps-8 text-xs"
                  />
                </div>
                <div className="max-h-56 overflow-y-auto">
                  {contextReplaceOptions
                    .filter((e) => e.type !== contextNode.type)
                    .filter((e) =>
                      e.label
                        .toLowerCase()
                        .includes(replaceQuery.trim().toLowerCase()),
                    )
                    .map((entry) => (
                      <button
                        key={entry.type}
                        type="button"
                        className="flex w-full items-center px-2.5 py-1.5 text-left text-sm hover:bg-accent"
                        onClick={() => {
                          handleReplace(contextNode.id, entry.type);
                          setContextMenu(null);
                        }}
                      >
                        {entry.label}
                      </button>
                    ))}
                  {contextReplaceOptions
                    .filter((e) => e.type !== contextNode.type)
                    .filter((e) =>
                      e.label
                        .toLowerCase()
                        .includes(replaceQuery.trim().toLowerCase()),
                    ).length === 0 && (
                    <p className="px-2.5 py-2 text-center text-xs text-muted-foreground">
                      No matching types.
                    </p>
                  )}
                </div>
              </>
            )}
          </div>
        </>
      )}
    </DndContext>
  );
}
