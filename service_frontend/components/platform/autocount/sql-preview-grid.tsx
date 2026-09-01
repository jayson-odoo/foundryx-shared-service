'use client';

import { LoaderCircleIcon, TriangleAlert } from 'lucide-react';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { ClampedText } from '@/components/platform/clamped-text';
import type { SqlPreviewState } from '@/hooks/use-autocount-etl';

export interface SqlPreviewGridProps {
  state: SqlPreviewState;
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

/**
 * The Test Query result grid (AC-22-06/07): column names + reported types in
 * the header, ≤ 100 rows, and every designed state - idle, loading, error
 * (sanitized), empty (0 rows still shows the columns) and success.
 */
export function SqlPreviewGrid({ state }: SqlPreviewGridProps) {
  if (state.status === 'idle') {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-dashed border-border py-10 text-sm text-muted-foreground"
        data-testid="sql-preview-idle"
      >
        No preview yet.
      </div>
    );
  }

  if (state.status === 'loading') {
    return (
      <div
        className="flex items-center justify-center gap-2 rounded-lg border border-border py-10 text-sm text-muted-foreground"
        data-testid="sql-preview-loading"
      >
        <LoaderCircleIcon className="size-4 animate-spin" />
        Running query…
      </div>
    );
  }

  if (state.status === 'error') {
    return (
      <Alert variant="destructive" appearance="light" data-testid="sql-preview-error">
        <AlertIcon>
          <TriangleAlert />
        </AlertIcon>
        <AlertTitle>{state.message}</AlertTitle>
      </Alert>
    );
  }

  const { columns, rows } = state.preview;

  return (
    <div className="flex flex-col gap-2" data-testid="sql-preview-success">
      {/* Scrolls within a bounded height - 100 rows must never push the
          column pickers below the fold (side panels never stretch the page). */}
      <div className="max-h-[26rem] overflow-auto rounded-lg border border-border">
        <table className="w-full min-w-max border-collapse text-xs">
          <thead className="sticky top-0 z-10">
            <tr className="bg-muted">
              {columns.map((col) => (
                <th
                  key={col.name}
                  className="whitespace-nowrap border-b border-border px-3 py-2 text-left align-top font-medium text-muted-foreground"
                  scope="col"
                >
                  <span className="block text-foreground">{col.name}</span>
                  <span className="block font-mono text-[10px] font-normal text-muted-foreground">
                    {col.type}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-border/60 last:border-b-0">
                {columns.map((col) => {
                  const raw = row[col.name];
                  const isNull = raw === null || raw === undefined;
                  const numeric = typeof raw === 'number';
                  return (
                    <td
                      key={col.name}
                      className={
                        numeric
                          ? 'whitespace-nowrap px-3 py-1.5 text-right font-mono tabular-nums'
                          : 'max-w-[18rem] px-3 py-1.5'
                      }
                    >
                      {isNull ? (
                        <span className="font-mono text-muted-foreground/70">NULL</span>
                      ) : (
                        <ClampedText text={cellText(raw)} lines={1} />
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && (
          <div
            className="py-8 text-center text-sm text-muted-foreground"
            data-testid="sql-preview-empty"
          >
            Query returned no rows.
          </div>
        )}
      </div>
    </div>
  );
}
