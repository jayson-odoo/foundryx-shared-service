'use client';

import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import {
  DndContext,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  ChevronDown,
  ChevronRight,
  FolderPlus,
  FolderTree,
  GripVertical,
  Pencil,
  Plus,
  Search,
  Trash2,
} from 'lucide-react';
import {
  Toolbar,
  ToolbarActions,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { Button } from '@/components/ui/button';
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useCan } from '@/hooks/use-can';
import { useTerminology } from '@/hooks/use-terminology';
import { emsService } from '@/services/ems-service';
import type { ProductCategory } from '@/types/ems';

const ROOT_DROP_ID = '__root__';

interface TreeNode extends ProductCategory {
  children: TreeNode[];
}

/** Drop target that moves a dragged category up to the top level (no parent). */
function RootDropZone() {
  const drop = useDroppable({ id: ROOT_DROP_ID });
  return (
    <div
      ref={drop.setNodeRef}
      className={`mb-1 rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground transition ${
        drop.isOver ? 'border-primary bg-primary/10 text-primary' : 'border-border'
      }`}
    >
      Top level
    </div>
  );
}

function buildTree(rows: ProductCategory[]): TreeNode[] {
  const byId = new Map<string, TreeNode>();
  rows.forEach((r) => byId.set(r.id, { ...r, children: [] }));
  const roots: TreeNode[] = [];
  byId.forEach((node) => {
    if (node.parentId && byId.has(node.parentId)) byId.get(node.parentId)!.children.push(node);
    else roots.push(node);
  });
  return roots;
}

function descendantIds(id: string, rows: ProductCategory[]): Set<string> {
  const out = new Set<string>([id]);
  let added = true;
  while (added) {
    added = false;
    for (const r of rows) {
      if (r.parentId && out.has(r.parentId) && !out.has(r.id)) {
        out.add(r.id);
        added = true;
      }
    }
  }
  return out;
}

/** Filter a tree to nodes matching `q` (or with a matching descendant). */
function filterTree(nodes: TreeNode[], q: string): TreeNode[] {
  if (!q) return nodes;
  const lower = q.toLowerCase();
  const walk = (n: TreeNode): TreeNode | null => {
    const kids = n.children.map(walk).filter(Boolean) as TreeNode[];
    if (n.name.toLowerCase().includes(lower) || kids.length) return { ...n, children: kids };
    return null;
  };
  return nodes.map(walk).filter(Boolean) as TreeNode[];
}

export default function CategoriesPage() {
  const { can } = useCan();
  const router = useRouter();
  const { labelPlural } = useTerminology();
  const [rows, setRows] = useState<ProductCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [deleting, setDeleting] = useState<ProductCategory | null>(null);
  const manage = can('product_categories.manage');
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  const load = useCallback(() => {
    setLoading(true);
    return emsService
      .listCategories()
      .then(setRows)
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Could not load categories.'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const tree = useMemo(() => filterTree(buildTree(rows), search.trim()), [rows, search]);
  const searching = search.trim().length > 0;

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const onDragEnd = async (e: DragEndEvent) => {
    const activeId = String(e.active.id);
    const overId = e.over ? String(e.over.id) : null;
    if (!overId || overId === activeId) return;
    const active = rows.find((r) => r.id === activeId);
    // Drop on the "Top level" zone → make it a root (no parent).
    if (overId === ROOT_DROP_ID) {
      if (active && !active.parentId) return; // already top-level
      try {
        await emsService.updateCategory(activeId, { parentId: null });
        load();
      } catch (err) {
        toast.error(err instanceof Error ? err.message : 'Could not move.');
      }
      return;
    }
    if (descendantIds(activeId, rows).has(overId)) {
      toast.error("Can't move a category into its own descendant.");
      return;
    }
    if (active && active.parentId === overId) return; // already there
    try {
      await emsService.updateCategory(activeId, { parentId: overId });
      setExpanded((prev) => new Set(prev).add(overId));
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not move.');
    }
  };

  return (
    <RequirePermission permission="product_categories.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle text={labelPlural('product_category')} />
              <ToolbarDescription>Organize your catalog into a taxonomy tree.</ToolbarDescription>
            </ToolbarHeading>
            {manage && (
              <ToolbarActions>
                <Button onClick={() => router.push('/ems/categories/new')}>
                  <Plus className="size-4" /> New category
                </Button>
              </ToolbarActions>
            )}
          </Toolbar>
        </Container>
        <Container width="fluid">
          <div className="rounded-xl border border-border bg-card">
            <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
              <Search className="size-4 text-muted-foreground" />
              <input
                className="w-full max-w-sm bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                placeholder="Search categories…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="p-2">
              {loading ? (
                <div className="py-16 text-center text-sm text-muted-foreground">Loading…</div>
              ) : tree.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-16 text-center">
                  <FolderTree className="size-8 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">
                    {searching ? 'No categories match.' : 'No categories yet.'}
                  </p>
                </div>
              ) : (
                <DndContext sensors={sensors} onDragEnd={onDragEnd}>
                  {manage && <RootDropZone />}
                  <ul className="flex flex-col">
                    {tree.map((node) => (
                      <TreeRow
                        key={node.id}
                        node={node}
                        depth={0}
                        expanded={expanded}
                        forceOpen={searching}
                        onToggle={toggle}
                        manage={manage}
                        onOpen={(id) => router.push(`/ems/categories/${id}`)}
                        onAddSub={(id) => router.push(`/ems/categories/new?parentId=${id}`)}
                        onDelete={(n) => setDeleting(n)}
                      />
                    ))}
                  </ul>
                </DndContext>
              )}
            </div>
          </div>
        </Container>

        {deleting && (
          <AlertDialog open onOpenChange={(o) => !o && setDeleting(null)}>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Delete “{deleting.name}”?</AlertDialogTitle>
                <AlertDialogDescription>
                  A category with sub-categories or products can’t be deleted.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  onClick={async () => {
                    try {
                      await emsService.deleteCategory(deleting.id);
                      toast.success('Category deleted.');
                      setDeleting(null);
                      load();
                    } catch (e) {
                      toast.error(e instanceof Error ? e.message : 'Could not delete.');
                      setDeleting(null);
                    }
                  }}
                >
                  Delete
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </Fragment>
    </RequirePermission>
  );
}

function TreeRow({
  node,
  depth,
  expanded,
  forceOpen,
  onToggle,
  manage,
  onOpen,
  onAddSub,
  onDelete,
}: {
  node: TreeNode;
  depth: number;
  expanded: Set<string>;
  forceOpen: boolean;
  onToggle: (id: string) => void;
  manage: boolean;
  onOpen: (id: string) => void;
  onAddSub: (id: string) => void;
  onDelete: (n: ProductCategory) => void;
}) {
  const hasChildren = node.children.length > 0;
  const isOpen = forceOpen || expanded.has(node.id);
  const drag = useDraggable({ id: node.id });
  const drop = useDroppable({ id: node.id });
  return (
    <li>
      <div
        ref={drop.setNodeRef}
        className={`group flex items-center gap-1 rounded-md px-2 py-1.5 hover:bg-accent ${drop.isOver ? 'bg-primary/10 ring-1 ring-primary/40' : ''}`}
        style={{ paddingInlineStart: depth * 20 + 8 }}
      >
        <button
          type="button"
          aria-label={hasChildren ? (isOpen ? 'Collapse' : 'Expand') : undefined}
          onClick={() => hasChildren && onToggle(node.id)}
          className="flex size-5 items-center justify-center text-muted-foreground"
        >
          {hasChildren ? (
            isOpen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />
          ) : (
            <span className="inline-block size-4" />
          )}
        </button>
        {manage && (
          <button
            type="button"
            aria-label="Drag to move"
            ref={drag.setNodeRef}
            {...drag.listeners}
            {...drag.attributes}
            className="flex size-5 cursor-grab items-center justify-center text-muted-foreground/60 hover:text-muted-foreground"
          >
            <GripVertical className="size-4" />
          </button>
        )}
        <button type="button" className="flex-1 text-start text-sm hover:underline" onClick={() => onOpen(node.id)}>
          {node.name}
        </button>
        {manage && (
          <div className="opacity-0 transition group-hover:opacity-100">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" aria-label="Category actions">…</Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => onAddSub(node.id)}>
                  <FolderPlus className="size-4" /> Add sub-category
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onOpen(node.id)}>
                  <Pencil className="size-4" /> Open
                </DropdownMenuItem>
                <DropdownMenuItem variant="destructive" onClick={() => onDelete(node)}>
                  <Trash2 className="size-4" /> Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      </div>
      {hasChildren && isOpen && (
        <ul className="flex flex-col">
          {node.children.map((c) => (
            <TreeRow
              key={c.id}
              node={c}
              depth={depth + 1}
              expanded={expanded}
              forceOpen={forceOpen}
              onToggle={onToggle}
              manage={manage}
              onOpen={onOpen}
              onAddSub={onAddSub}
              onDelete={onDelete}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
