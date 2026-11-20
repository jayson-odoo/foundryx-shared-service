'use client';

/**
 * Left palette (plan sprint-2/08 D15, search + collapse in 09) - triggers /
 * logic / actions grouped into collapsible sections (collapsed by default so
 * the growing catalog stays compact) with a search box that filters across all
 * sections and auto-expands matches. Each item is a dnd-kit draggable AND a
 * click-to-add button - click is the E2E path (dnd-kit pointer sensors aren't
 * drivable by scripted mouse-event drag automation - template-engine
 * lesson); drag is the nicety. Not asserted in jsdom; the drag/drop-onto-
 * canvas behaviour needs a recorded agent-browser check in any slice that
 * touches it. A trigger is disabled once one exists (one trigger per
 * workflow, D2).
 */
import { useMemo, useState } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { ChevronDown, Search, TriangleAlert, Zap } from 'lucide-react';
import {
  ACTION_CATALOG,
  IF_CATALOG,
  TRIGGER_CATALOG,
  deniedNodePermissions,
  isNodeTypeRegistered,
  isPermissionDenied,
} from '@/lib/workflow-catalog';
import { cn } from '@/lib/utils';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { Input } from '@/components/ui/input';
import { ClampedText } from '@/components/platform/clamped-text';
import { Skeleton } from '@/components/ui/skeleton';
import { useInstalledModules } from '@/hooks/use-app-store';
import type { NodeCatalogEntry, WorkflowCatalogStatus } from '@/types/workflows';
import { WORKFLOW_NODE_ICONS } from './workflow-icons';

/** A `module`-tagged entry is visible only while that module is ACTIVE for the
 * tenant (plan sprint-4/17) - `'core'`/absent is always visible. Mirrors the
 * backend `app/module_platform/active.py` `is_visible` predicate. */
function visibleEntries<T extends { module?: string }>(
  entries: T[],
  isActive: (name: string) => boolean,
): T[] {
  return entries.filter((e) => !e.module || e.module === 'core' || isActive(e.module));
}

const ICONS = WORKFLOW_NODE_ICONS;

interface PaletteItemProps {
  entry: NodeCatalogEntry;
  disabled: boolean;
  onAdd: (type: string) => void;
}

function PaletteItem({ entry, disabled, onAdd }: PaletteItemProps) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `palette-${entry.type}`,
    data: { source: 'palette', nodeType: entry.type },
    disabled,
  });
  const Icon = ICONS[entry.icon] ?? Zap;
  return (
    <button
      ref={setNodeRef}
      type="button"
      data-testid={`palette-${entry.type}`}
      disabled={disabled}
      onClick={() => !disabled && onAdd(entry.type)}
      className={cn(
        PRESSED_CLASS,
        'flex w-full items-center gap-2.5 rounded-lg border border-input bg-background p-2.5 text-left transition-colors',
        disabled ? 'cursor-not-allowed opacity-50' : 'cursor-grab hover:border-primary',
        isDragging && 'opacity-40',
      )}
      {...listeners}
      {...attributes}
    >
      <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-muted text-foreground">
        <Icon className="size-4" />
      </span>
      <span className="min-w-0">
        <span className="block text-xs font-medium text-foreground">{entry.label}</span>
        <ClampedText text={entry.description} lines={2} className="text-2xs leading-tight text-muted-foreground" />
      </span>
    </button>
  );
}

interface PaletteSection {
  title: string;
  entries: NodeCatalogEntry[];
  /** Disable all items in this section (triggers once one exists). */
  itemsDisabled?: boolean;
}

function matches(entry: NodeCatalogEntry, q: string): boolean {
  return (
    entry.label.toLowerCase().includes(q) ||
    entry.description.toLowerCase().includes(q) ||
    entry.type.toLowerCase().includes(q)
  );
}

export interface NodePaletteProps {
  /** True when a trigger already exists - disables trigger items. */
  hasTrigger: boolean;
  disabled: boolean;
  onAdd: (type: string) => void;
  /** Permission snapshot supplied by the page. Defaults true for isolated UI use. */
  canCode?: boolean;
  /** Gates the HTTP request node (`workflows.http`), same as `canCode`. */
  canHttp?: boolean;
  /** Every trigger/action type the backend registry currently resolves
   * (`GET /workflows/metadata`, plan 31 S3 review B-4) - a catalog entry
   * absent here is OMITTED entirely (never shown-then-disabled). */
  registeredNodeTypes?: string[];
  /** Load state of that metadata call. `loading` shows a skeleton, `error`
   * shows an inline retry-less failure state - never a silently empty
   * palette (review round 2, R-2). Defaults to `ready` for isolated UI use. */
  catalogStatus?: WorkflowCatalogStatus;
}

export function NodePalette({
  hasTrigger,
  disabled,
  onAdd,
  canCode = true,
  canHttp = true,
  registeredNodeTypes,
  catalogStatus = 'ready',
}: NodePaletteProps) {
  const [query, setQuery] = useState('');
  // Sections collapsed by default - the catalog is long; expand on click/search.
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const { isActive } = useInstalledModules();
  const denied = useMemo(
    () => deniedNodePermissions({ code: canCode, http: canHttp }),
    [canCode, canHttp],
  );

  // Logic = the IF node + any action catalogued under the "Logic" category
  // (Wait, Business hours - D-A5-19) - flow-control actions live with the
  // other branching/pausing primitive, not buried in the long Actions list.
  const sections: PaletteSection[] = useMemo(() => {
    const registered = <T extends NodeCatalogEntry>(entries: T[]) =>
      entries.filter((e) => isNodeTypeRegistered(e, registeredNodeTypes));
    const actions = registered(visibleEntries(ACTION_CATALOG, isActive));
    return [
      {
        title: 'Triggers',
        entries: registered(visibleEntries(TRIGGER_CATALOG, isActive)),
        itemsDisabled: hasTrigger,
      },
      {
        title: 'Logic',
        entries: [...IF_CATALOG, ...actions.filter((e) => e.category === 'Logic')],
      },
      { title: 'Actions', entries: actions.filter((e) => e.category !== 'Logic') },
    ];
  }, [hasTrigger, isActive, registeredNodeTypes]);

  const q = query.trim().toLowerCase();
  const searching = q.length > 0;

  if (catalogStatus === 'loading') {
    return (
      <div className="flex flex-col gap-3" data-testid="node-palette-loading">
        <Skeleton className="h-8 w-full" />
        {[0, 1, 2].map((row) => (
          <div key={row} className="flex flex-col gap-1.5">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ))}
      </div>
    );
  }

  if (catalogStatus === 'error') {
    return (
      <div
        className="flex flex-col items-center gap-2 px-1 py-6 text-center"
        data-testid="node-palette-error"
      >
        <TriangleAlert className="size-5 text-muted-foreground" />
        <p className="text-xs text-muted-foreground">
          The node catalog could not be loaded.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3" data-testid="node-palette">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search nodes…"
          aria-label="Search nodes"
          data-testid="palette-search"
          className="h-8 ps-8 text-xs"
        />
      </div>

      {sections.map((section) => {
        const entries = searching ? section.entries.filter((e) => matches(e, q)) : section.entries;
        if (searching && entries.length === 0) return null;
        const expanded = searching || open[section.title];
        return (
          <div key={section.title} className="flex flex-col gap-1.5">
            <button
              type="button"
              data-testid={`palette-section-${section.title.toLowerCase()}`}
              onClick={() => setOpen((s) => ({ ...s, [section.title]: !s[section.title] }))}
              className={cn(PRESSED_CLASS, 'flex items-center justify-between rounded-md px-0.5 py-1 text-left')}
              aria-expanded={Boolean(expanded)}
            >
              <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {section.title}
                <span className="ms-1.5 font-normal normal-case">({entries.length})</span>
              </span>
              <ChevronDown
                className={cn(
                  'size-3.5 text-muted-foreground transition-transform',
                  expanded ? 'rotate-0' : '-rotate-90',
                )}
              />
            </button>
            {expanded &&
              entries.map((entry) => (
                  <PaletteItem
                    key={entry.type}
                    entry={entry}
                    disabled={
                      disabled ||
                      (section.itemsDisabled ?? false) ||
                      isPermissionDenied(entry, denied)
                    }
                  onAdd={onAdd}
                />
              ))}
          </div>
        );
      })}

      {searching &&
        sections.every((s) => s.entries.filter((e) => matches(e, q)).length === 0) && (
          <p className="px-1 py-2 text-center text-xs text-muted-foreground">No matching nodes.</p>
        )}
    </div>
  );
}
