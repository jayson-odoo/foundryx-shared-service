'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  Database,
  LoaderCircleIcon,
  RefreshCw,
  Search,
  SquarePlus,
  Table2,
  TriangleAlert,
  UnfoldVertical,
} from 'lucide-react';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ClampedText } from '@/components/platform/clamped-text';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { cn } from '@/lib/utils';
import type { AutocountSqlSchema, AutocountSqlTable } from '@/types/autocount';

export interface SqlSchemaTreeProps {
  schema: AutocountSqlSchema | null;
  isLoading: boolean;
  /** Sanitized failure message (connect refused, login failed...). */
  error: string | null;
  /** True while no connection is chosen - the tree has nothing to show. */
  noConnection?: boolean;
  onRefresh: () => void;
  /** Insert the starter `SELECT * FROM <schema>.<table>` (AC-22-07). */
  onInsertQuery: (schemaName: string, tableName: string) => void;
  /** False in read mode - the insert action is withheld, not failed. */
  canInsert: boolean;
  className?: string;
}

interface SelectedTable {
  schemaName: string;
  table: AutocountSqlTable;
}

/**
 * The Query tab's left panel (AC-22-07): searchable schema → tables tree
 * (tables only), Expand all, Refresh (busts the server cache), and a columns
 * side panel for the clicked table with the starter-query action.
 */
export function SqlSchemaTree({
  schema,
  isLoading,
  error,
  noConnection = false,
  onRefresh,
  onInsertQuery,
  canInsert,
  className,
}: SqlSchemaTreeProps) {
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<SelectedTable | null>(null);

  // A fresh schema (new connection / refresh) opens its first namespace and
  // drops a selection that may no longer exist.
  useEffect(() => {
    setExpanded(new Set(schema?.schemas[0] ? [schema.schemas[0].name] : []));
    setSelected(null);
  }, [schema]);

  const term = search.trim().toLowerCase();
  const filtered = useMemo(() => {
    if (!schema) return [];
    return schema.schemas
      .map((node) => ({
        name: node.name,
        tables: term
          ? node.tables.filter((t) => t.name.toLowerCase().includes(term))
          : node.tables,
      }))
      .filter((node) => !term || node.tables.length > 0);
  }, [schema, term]);

  const allExpanded =
    filtered.length > 0 && filtered.every((node) => expanded.has(node.name));

  const toggleAll = () => {
    setExpanded(allExpanded ? new Set() : new Set(filtered.map((n) => n.name)));
  };

  const toggle = (name: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  // While searching every match is visible regardless of the collapse state -
  // a hit hidden under a collapsed node would read as "no match".
  const isOpen = (name: string) => Boolean(term) || expanded.has(name);

  return (
    <div className={className} data-testid="sql-schema-tree">
      <div className="flex flex-col gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search tables"
            className="h-8 pl-8 text-xs"
            aria-label="Search tables"
            disabled={!schema}
          />
        </div>
        <div className="flex items-center justify-between gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={toggleAll}
            disabled={!schema || filtered.length === 0}
          >
            <UnfoldVertical className="size-3.5" />
            {allExpanded ? 'Collapse all' : 'Expand all'}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={onRefresh}
            disabled={noConnection || isLoading}
            aria-label="Refresh schema"
          >
            <RefreshCw className={isLoading ? 'size-3.5 animate-spin' : 'size-3.5'} />
            Refresh
          </Button>
        </div>
      </div>

      <div className="mt-2 min-h-24 text-xs">
        {noConnection && (
          <p className="py-6 text-center text-muted-foreground">No connection selected.</p>
        )}
        {!noConnection && isLoading && !schema && (
          <div
            className="flex items-center justify-center gap-2 py-6 text-muted-foreground"
            data-testid="sql-schema-loading"
          >
            <LoaderCircleIcon className="size-4 animate-spin" />
            Loading schema…
          </div>
        )}
        {!noConnection && error && (
          <Alert variant="destructive" appearance="light" size="sm" data-testid="sql-schema-error">
            <AlertIcon>
              <TriangleAlert />
            </AlertIcon>
            <AlertTitle>{error}</AlertTitle>
          </Alert>
        )}
        {schema && !error && (
          <ul className="flex flex-col gap-0.5" role="tree" aria-label="Tables">
            <li className="flex items-center gap-1.5 px-1 py-1 font-medium text-foreground">
              <Database className="size-3.5 text-muted-foreground" />
              <ClampedText text={schema.database} lines={1} />
            </li>
            {filtered.length === 0 && (
              <li className="px-1 py-4 text-center text-muted-foreground">No tables match.</li>
            )}
            {filtered.map((node) => (
              <li
                key={node.name}
                role="treeitem"
                aria-expanded={isOpen(node.name)}
                aria-selected={false}
              >
                <button
                  type="button"
                  className={cn(PRESSED_CLASS, 'flex w-full items-center gap-1 rounded px-1 py-1 text-left hover:bg-muted')}
                  onClick={() => toggle(node.name)}
                >
                  {isOpen(node.name) ? (
                    <ChevronDown className="size-3.5 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="size-3.5 text-muted-foreground" />
                  )}
                  <span className="font-medium">{node.name}</span>
                  <span className="ml-auto text-muted-foreground">{node.tables.length}</span>
                </button>
                {isOpen(node.name) && (
                  <ul className="ml-3 flex flex-col border-l border-border pl-2" role="group">
                    {node.tables.map((table) => {
                      const isSelected =
                        selected?.schemaName === node.name &&
                        selected.table.name === table.name;
                      return (
                        <li key={table.name} role="treeitem" aria-selected={isSelected}>
                          <button
                            type="button"
                            className={cn(
                              PRESSED_CLASS,
                              isSelected
                                ? 'flex w-full items-center gap-1.5 rounded bg-primary/10 px-1.5 py-1 text-left font-medium text-primary'
                                : 'flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left hover:bg-muted',
                            )}
                            onClick={() => setSelected({ schemaName: node.name, table })}
                          >
                            <Table2 className="size-3.5 shrink-0 text-muted-foreground" />
                            <ClampedText text={table.name} lines={1} />
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {selected && (
        <div
          className="mt-3 rounded-lg border border-border bg-background p-2.5"
          data-testid="sql-columns-panel"
        >
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="min-w-0 text-2xs font-semibold uppercase tracking-wide text-muted-foreground">
              <ClampedText text={`Columns · ${selected.table.name}`} lines={1} />
            </span>
            <span className="text-2xs text-muted-foreground">
              {selected.table.columns.length}
            </span>
          </div>
          <ul className="flex max-h-56 flex-col gap-0.5 overflow-y-auto">
            {selected.table.columns.map((col) => (
              <li key={col.name} className="flex items-baseline justify-between gap-2 font-mono text-2xs">
                <span className="min-w-0 text-foreground">
                  <ClampedText text={col.name} lines={1} />
                </span>
                <span className="shrink-0 text-muted-foreground">{col.type}</span>
              </li>
            ))}
          </ul>
          {canInsert && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-2.5 h-7 w-full text-xs"
              onClick={() => onInsertQuery(selected.schemaName, selected.table.name)}
              data-testid="sql-insert-starter"
            >
              <SquarePlus className="size-3.5" />
              Insert SELECT *
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
