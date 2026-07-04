'use client';

/**
 * One entity's transition-graph editor (sprint-2/01, reworked per review):
 * controlled nodes/edges (drag applies locally = smooth; position saves are
 * silent), click an edge to SELECT it (floating Edit/Delete toolbar +
 * Delete key), click a node to edit it in the drawer. The form's global Edit
 * toggle gates every mutation — read-only flow view by default.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSession } from 'next-auth/react';
import {
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  MarkerType,
  type Node,
  type NodeChange,
  type ReactFlowInstance,
} from '@xyflow/react';
import { Pencil, Plus, Redo2, Trash2, Undo2, Wand2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { FlowCanvas, layoutGraph, OffsetEdge, useHistory } from '@/components/platform/flow-canvas';
import type { MultiSelectOption } from '@/components/platform/multi-select';
import type { UseStatusGraphResult } from '@/hooks/use-status-engine';
import { rolesService } from '@/services/roles-service';
import { ruleEngineService } from '@/services/rule-engine-service';
import { templateEngineService } from '@/services/template-service';
import { userService } from '@/services/user-service';
import { templateDocToText } from '@/lib/template-to-text';

/** Template-engine context backing transition-notification templates (BL-081). */
const NOTIFICATION_CONTEXT = 'status.notification';
import type { RuleFact } from '@/types/rules';
import type {
  StatusNodeData,
  StatusTransition,
  TransitionNotification,
} from '@/types/status-engine';
import { isCanvasDoc } from '@/types/templates';
import { StatusDrawer } from './status-drawer';
import { StatusFlowNode } from './status-node';
import { TransitionDrawer, type PendingEdge } from './transition-drawer';

const NODE_TYPES = { status: StatusFlowNode };
const EDGE_TYPES = { offset: OffsetEdge };

/** Fallback grid layout for nodes without a saved canvas position. */
function autoPosition(index: number): { x: number; y: number } {
  return { x: (index % 4) * 240 + 40, y: Math.floor(index / 4) * 160 + 40 };
}

type Pos = { x: number; y: number };
const samePos = (a?: Pos, b?: Pos) => !!a && !!b && a.x === b.x && a.y === b.y;

/** Imperative handle the ResourceForm's Save/Cancel drive (BL-064). */
export interface LayoutController {
  save: () => void;
  discard: () => void;
}

export interface EntityFlowProps {
  entityType: string;
  /** Display label of the entity (drawer template previews). */
  entityLabel?: string;
  engine: UseStatusGraphResult;
  /** Form global Edit toggle state — false = read-only flow view. */
  editing: boolean;
  /** True when the layout draft has unsaved moves — feeds the form dirty-guard. */
  onDirtyChange?: (dirty: boolean) => void;
  /** The form's Save persists the layout; Cancel discards it (revert positions). */
  layoutController?: React.MutableRefObject<LayoutController | null>;
}

export function EntityFlow({
  entityType,
  entityLabel,
  engine,
  editing,
  onDirtyChange,
  layoutController,
}: EntityFlowProps) {
  const { data: session } = useSession();
  const graph = engine.graph;
  const statuses = useMemo(() => graph?.statuses ?? [], [graph]);

  // A cosmetic drag must NEVER trigger the fork-on-first-edit (code-review
  // fix): persist positions only when the visible tier is already the
  // caller's to write — platform operators own the platform tier; tenants
  // own their fork. A tenant dragging on inherited defaults keeps the layout
  // locally for the session, nothing persists.
  const canPersistPositions =
    Boolean(session?.user?.isPlatformTenant) || graph?.source === 'tenant';

  // Controlled canvas state — drags/selection apply locally (no jank).
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [flowInstance, setFlowInstance] = useState<ReactFlowInstance | null>(null);

  // ---- layout draft + undo/redo (BL-064) -----------------------------------
  // Positions are a CLIENT DRAFT — drags and Tidy mutate `layout` through the
  // shared history hook (undo/redo), and persist only on "Save layout" (or are
  // discarded). `baseline` = the server-saved positions; a node is "dirty"
  // purely by `layout` differing from `baseline`, so undo / dragging a node
  // back to its origin self-corrects the dirty count (no monotonic bookkeeping).
  const [layout, setLayout] = useState<Record<string, Pos>>({});
  const [baseline, setBaseline] = useState<Record<string, Pos>>({});
  const layoutHistory = useHistory(layout, setLayout);
  // Read latest layout/baseline inside the reseed effect without re-subscribing.
  const layoutRef = useRef(layout);
  layoutRef.current = layout;
  const baselineRef = useRef(baseline);
  baselineRef.current = baseline;

  const dirtyIds = useMemo(
    () => statuses.map((s) => s.id).filter((id) => !samePos(layout[id], baseline[id])),
    [statuses, layout, baseline],
  );
  const dirtyCount = dirtyIds.length;

  const [selectedStatus, setSelectedStatus] = useState<StatusNodeData | null>(null);
  const [statusDrawerOpen, setStatusDrawerOpen] = useState(false);
  const [selectedTransition, setSelectedTransition] = useState<StatusTransition | null>(null);
  const [pendingEdge, setPendingEdge] = useState<PendingEdge | null>(null);
  const [transitionDrawerOpen, setTransitionDrawerOpen] = useState(false);
  const [roleOptions, setRoleOptions] = useState<MultiSelectOption[]>([]);
  const [userOptions, setUserOptions] = useState<MultiSelectOption[]>([]);
  const [templateOptions, setTemplateOptions] = useState<MultiSelectOption[]>([]);
  const [ruleFacts, setRuleFacts] = useState<RuleFact[]>([]);

  // Pickers for edge roles + USER recipients + notification templates — load
  // once, fail quiet.
  useEffect(() => {
    rolesService
      .list()
      .then((roles) => setRoleOptions(roles.map((r) => ({ value: r.id, label: r.name }))))
      .catch(() => undefined);
    userService
      .list({ page: 0, pageSize: 100 })
      .then((result) =>
        setUserOptions(result.data.map((u) => ({ value: u.id, label: u.name || u.email }))),
      )
      .catch(() => undefined);
    templateEngineService
      .listTemplateOptions(NOTIFICATION_CONTEXT)
      .then((rows) => setTemplateOptions(rows.map((t) => ({ value: t.id, label: t.name }))))
      .catch(() => undefined);
  }, []);

  // Whitelisted rule facts for edge conditions (sprint-2/02) — the consumer
  // declares its sources: the acting user + this entity's record (D2).
  useEffect(() => {
    ruleEngineService
      .getFacts(['actor', `record:${entityType}`])
      .then(setRuleFacts)
      .catch(() => undefined);
  }, [entityType]);

  // Reseed from the server graph (structural changes refetch). `baseline`
  // becomes the new server truth; an UNSAVED drag (layout ≠ old baseline)
  // survives the refetch, every other node snaps to its server position.
  // Reseeding through setLayout (not the history setter) resets the undo
  // timeline — a structural change is a new editing session.
  useEffect(() => {
    const serverMap: Record<string, Pos> = {};
    statuses.forEach((status, index) => {
      serverMap[status.id] =
        status.positionX != null && status.positionY != null
          ? { x: status.positionX, y: status.positionY }
          : autoPosition(index);
    });
    const prevLayout = layoutRef.current;
    const prevBaseline = baselineRef.current;
    setLayout(() => {
      const next: Record<string, Pos> = {};
      statuses.forEach((status) => {
        const dragged =
          prevLayout[status.id] && !samePos(prevLayout[status.id], prevBaseline[status.id]);
        next[status.id] = dragged ? prevLayout[status.id] : serverMap[status.id];
      });
      return next;
    });
    setBaseline(serverMap);
  }, [statuses]);

  // Build canvas nodes from the layout draft (positions) + the server graph.
  useEffect(() => {
    setNodes(
      statuses.map((status, index) => ({
        id: status.id,
        type: 'status',
        position:
          layout[status.id] ??
          (status.positionX != null && status.positionY != null
            ? { x: status.positionX, y: status.positionY }
            : autoPosition(index)),
        data: { status },
        deletable: false, // nodes delete via their drawer, never the Delete key
      })),
    );
  }, [statuses, layout]);

  // Build canvas edges from the server graph (structural changes refetch).
  useEffect(() => {
    const transitions = graph?.transitions ?? [];
    const edgeKeys = new Set(transitions.map((t) => `${t.fromStatusId}->${t.toStatusId}`));
    setEdges(
      transitions.map((transition) => {
        // Opposite-direction pairs (Suspend vs Reactivate) bow apart so their
        // paths AND labels never overlap (review feedback). The same positive
        // offset bows each direction to its own side.
        const hasReverse = edgeKeys.has(
          `${transition.toStatusId}->${transition.fromStatusId}`,
        );
        // Derived status (sprint-4/03) — auto edges are system-fired: render
        // distinctly (dashed, primary, ⚡ prefix) and never as an action button.
        const isAuto = transition.triggerMode === 'auto';
        return {
          id: transition.id,
          source: transition.fromStatusId,
          target: transition.toStatusId,
          label: isAuto ? `⚡ ${transition.label}` : transition.label,
          type: 'offset',
          markerEnd: { type: MarkerType.ArrowClosed, width: 20, height: 20 },
          style: isAuto
            ? { strokeWidth: 1.5, strokeDasharray: '6 4', stroke: 'var(--primary)' }
            : { strokeWidth: 1.5 },
          data: {
            offset: hasReverse ? 45 : 0,
            // Label clicks bypass RF's pane handling — mirror the selection
            // into RF state too, so the stroke highlights and the Delete key
            // targets the edge (code-review fix).
            onSelect: (edgeId: string) => {
              setSelectedEdgeId(edgeId);
              setEdges((current) =>
                current.map((e) => ({ ...e, selected: e.id === edgeId })),
              );
            },
          },
          deletable: true,
        };
      }),
    );
    setSelectedEdgeId(null);
  }, [graph, statuses]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => setNodes((current) => applyNodeChanges(changes, current)),
    [],
  );
  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      setEdges((current) => applyEdgeChanges(changes, current));
      for (const change of changes) {
        if (change.type === 'select') {
          setSelectedEdgeId(change.selected ? change.id : null);
        }
      }
    },
    [],
  );

  // Keyboard undo/redo for the layout draft (skips while typing in a field or
  // on an interactive control — same guard as the workflow canvas).
  useEffect(() => {
    if (!editing) return;
    const handler = (e: KeyboardEvent) => {
      const isUndoRedo =
        (e.metaKey || e.ctrlKey) && (e.key.toLowerCase() === 'z' || e.key.toLowerCase() === 'y');
      if (!isUndoRedo) return;
      const target = e.target as HTMLElement | null;
      if (target?.closest('input, textarea, [contenteditable="true"], [role="combobox"]')) return;
      e.preventDefault();
      if (e.key.toLowerCase() === 'y' || e.shiftKey) layoutHistory.redo();
      else layoutHistory.undo();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [editing, layoutHistory]);

  // Re-fit the viewport when the node COUNT changes (a status added/removed) —
  // React Flow only fits at mount, so a freshly-created node (grid-positioned,
  // outside the initial fit) would otherwise land off-screen. Position-only
  // drags don't change the count, so this never fights a manual layout.
  const nodeCountRef = useRef(nodes.length);
  useEffect(() => {
    if (nodes.length !== nodeCountRef.current) {
      nodeCountRef.current = nodes.length;
      if (flowInstance) {
        requestAnimationFrame(() => flowInstance.fitView({ padding: 0.2, duration: 300 }));
      }
    }
  }, [nodes.length, flowInstance]);

  const openStatus = (status: StatusNodeData) => {
    setSelectedStatus(status);
    setStatusDrawerOpen(true);
  };

  const openTransition = (transition: StatusTransition) => {
    setPendingEdge(null);
    setSelectedTransition(transition);
    setTransitionDrawerOpen(true);
  };

  const onConnect = (connection: Connection) => {
    if (!editing || !connection.source || !connection.target) return;
    if (connection.source === connection.target) return; // no self-loops (D4)
    setSelectedTransition(null);
    setPendingEdge({ fromStatusId: connection.source, toStatusId: connection.target });
    setTransitionDrawerOpen(true);
  };

  const selectedEdgeTransition = useMemo(
    () => graph?.transitions.find((t) => t.id === selectedEdgeId) ?? null,
    [graph, selectedEdgeId],
  );

  const cloneNotifications = (notifications: TransitionNotification[]) =>
    notifications.map((n) => ({ ...n, recipients: n.recipients.map((r) => ({ ...r })) }));

  // Copy a template's block doc (+ subject, + flattened body fallback) for
  // per-use editing — branded, but the wording is editable on the transition.
  const loadTemplate = useCallback(async (id: string) => {
    const template = await templateEngineService.getTemplate(id);
    // The notification picker lists only EMAIL templates — a canvas (badge) doc
    // can't back a transition mail.
    if (!template || isCanvasDoc(template.doc)) return null;
    return {
      subject: template.subject,
      body: templateDocToText(template.doc),
      doc: template.doc,
    };
  }, []);

  // A drag/Tidy just pushes a new layout draft through history; "dirty" is
  // derived (layout ≠ baseline), so nothing else to track.
  const pushLayout = useCallback(
    (next: Record<string, Pos>) => layoutHistory.set(next),
    [layoutHistory],
  );

  /** "Tidy" — layered auto-layout (initial → terminal, left to right). Now a
   * PREVIEW: it updates the draft (undoable) and never persists until Save. */
  const tidy = useCallback(() => {
    const arranged = layoutGraph(nodes, edges);
    const next: Record<string, Pos> = {};
    for (const node of arranged) next[node.id] = { x: node.position.x, y: node.position.y };
    pushLayout(next);
    requestAnimationFrame(() => flowInstance?.fitView({ padding: 0.2, duration: 300 }));
  }, [nodes, edges, flowInstance, pushLayout]);

  /** Persist every moved position, advance the baseline, drop the undo timeline.
   * Driven by the ResourceForm's Save (the layout is part of the form now). */
  const saveLayout = useCallback(() => {
    const current = layoutRef.current;
    const baseNow = baselineRef.current;
    if (canPersistPositions) {
      for (const id of Object.keys(current)) {
        if (!samePos(current[id], baseNow[id])) {
          engine.saveNodePosition(id, current[id].x, current[id].y);
        }
      }
    }
    setBaseline({ ...current });
    layoutHistory.reset();
  }, [canPersistPositions, engine, layoutHistory]);

  /** Revert the canvas to the server baseline (ResourceForm Cancel/Discard). */
  const discardLayout = useCallback(() => {
    setLayout({ ...baselineRef.current });
    layoutHistory.reset();
  }, [layoutHistory]);

  // Surface dirtiness + the save/discard handle to the parent ResourceForm so
  // its global Save/Cancel + unsaved-changes dialog own the layout draft.
  useEffect(() => {
    onDirtyChange?.(dirtyCount > 0);
  }, [dirtyCount, onDirtyChange]);
  useEffect(() => {
    if (layoutController) layoutController.current = { save: saveLayout, discard: discardLayout };
  }, [layoutController, saveLayout, discardLayout]);

  return (
    <div className="flex flex-col gap-3" data-testid="entity-flow">
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <Badge
          variant={graph?.source === 'tenant' ? 'primary' : 'secondary'}
          appearance="light"
        >
          {graph?.source === 'tenant' ? 'Customized' : 'Platform defaults'}
        </Badge>
        {editing && (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              mode="icon"
              aria-label="Undo"
              disabled={!layoutHistory.canUndo}
              onClick={layoutHistory.undo}
            >
              <Undo2 className="size-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              mode="icon"
              aria-label="Redo"
              disabled={!layoutHistory.canRedo}
              onClick={layoutHistory.redo}
            >
              <Redo2 className="size-4" />
            </Button>
            <Button variant="outline" size="sm" onClick={tidy}>
              <Wand2 className="size-4" /> Tidy
            </Button>
            <Button
              size="sm"
              onClick={() => {
                setSelectedStatus(null);
                setStatusDrawerOpen(true);
              }}
            >
              <Plus className="size-4" /> Add status
            </Button>
          </div>
        )}
      </div>

      <div className="relative">
        <FlowCanvas
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          edgeTypes={EDGE_TYPES}
          readOnly={!editing}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={editing ? onConnect : undefined}
          onNodeClick={(id) => {
            const status = statuses.find((s) => s.id === id);
            if (status) openStatus(status);
          }}
          onEdgeClick={(id) => setSelectedEdgeId(id)}
          onPaneClick={() => setSelectedEdgeId(null)}
          onNodeDragStop={(id, x, y) => {
            // Drags mutate the layout DRAFT (undoable); nothing persists until
            // "Save layout". On the inherited platform tier (can't persist) the
            // drag still moves locally for the session.
            if (!editing) return;
            pushLayout({ ...layoutRef.current, [id]: { x, y } });
          }}
          onInit={setFlowInstance}
          onEdgesDelete={
            editing
              ? (deleted) => {
                  for (const edge of deleted) void engine.deleteTransition(edge.id);
                }
              : undefined
          }
        />

        {/* Floating toolbar for the selected connection. */}
        {selectedEdgeTransition && (
          <div
            data-testid="edge-toolbar"
            className="absolute left-1/2 top-3 z-10 flex -translate-x-1/2 items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1.5 shadow-md"
          >
            <span className="max-w-48 truncate text-xs font-medium text-foreground">
              {selectedEdgeTransition.label}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => openTransition(selectedEdgeTransition)}
            >
              <Pencil className="size-3.5" /> {editing ? 'Edit' : 'View'}
            </Button>
            {editing && (
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive"
                onClick={() => void engine.deleteTransition(selectedEdgeTransition.id)}
              >
                <Trash2 className="size-3.5" /> Delete
              </Button>
            )}
          </div>
        )}
      </div>

      {editing && dirtyCount > 0 && (
        <p className="text-xs text-muted-foreground">
          {canPersistPositions
            ? `Unsaved layout — ${dirtyCount} ${dirtyCount === 1 ? 'node' : 'nodes'} moved.`
            : 'Layout changes apply to this view only (inherited defaults).'}
        </p>
      )}

      <StatusDrawer
        open={statusDrawerOpen}
        onOpenChange={setStatusDrawerOpen}
        status={selectedStatus}
        statuses={statuses}
        canManage={editing}
        onCreate={(label, color, flags) =>
          engine.createStatus({ entityType, label, color, flags })
        }
        onUpdate={(id, label, color, flags) => engine.updateStatus(id, { label, color, flags })}
        onDelete={engine.deleteStatus}
        onSetActive={engine.setStatusActive}
        onMigrate={engine.migrateRecords}
      />

      <TransitionDrawer
        open={transitionDrawerOpen}
        onOpenChange={setTransitionDrawerOpen}
        transition={selectedTransition}
        pending={pendingEdge}
        statuses={statuses}
        entityLabel={entityLabel}
        roleOptions={roleOptions}
        userOptions={userOptions}
        templateOptions={templateOptions}
        onLoadTemplate={loadTemplate}
        facts={ruleFacts}
        canManage={editing}
        onCreate={(edge, label, roleIds, notifications, conditions, triggerMode) =>
          engine.createTransition({
            entityType,
            fromStatusId: edge.fromStatusId,
            toStatusId: edge.toStatusId,
            label,
            roleIds,
            notifications: cloneNotifications(notifications),
            conditionsJson: conditions,
            triggerMode,
          })
        }
        onUpdate={(id, label, roleIds, notifications, conditions, triggerMode) =>
          engine.updateTransition(id, {
            label,
            roleIds,
            notifications: cloneNotifications(notifications),
            conditionsJson: conditions,
            triggerMode,
          })
        }
        onDelete={engine.deleteTransition}
      />
    </div>
  );
}
