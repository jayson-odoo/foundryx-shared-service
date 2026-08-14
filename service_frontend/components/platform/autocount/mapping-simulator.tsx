'use client';

/**
 * Whole-mapping simulator (AC-16-30/31) - a mock AutoCount record in → the whole
 * Sorento record out, run through the REAL MappingEngine on the server. It sends
 * the CURRENT (possibly unsaved) editor rows so the operator previews their DRAFT
 * before a sync stages a broken batch. It writes NOTHING - a pure transform
 * preview, distinct from the slice-14 Sorento dry-run (which asks Sorento what a
 * push would do). Failing fields are shown with their per-field error, never
 * silently omitted.
 */
import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, LoaderCircle, Play, TriangleAlert } from 'lucide-react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import {
  Alert,
  AlertDescription,
  AlertIcon,
  AlertTitle,
} from '@/components/ui/alert';
import { cn } from '@/lib/utils';
import { humanizeFieldKey } from '@/lib/autocount-diff';
import type {
  AutocountMappingWriteRow,
  AutocountSimulateFieldResult,
  AutocountSimulateResult,
} from '@/types/autocount';

export interface MappingSimulatorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The CURRENT draft deliverable rows - sent so unsaved edits preview. */
  rows: AutocountMappingWriteRow[];
  /** Run the whole mapping over the mock record (writes nothing). */
  onSimulate: (
    record: Record<string, unknown>,
    rows: AutocountMappingWriteRow[],
  ) => Promise<AutocountSimulateResult>;
  entityLabel?: string;
}

/** A flat starting skeleton from the top-level (non-dotted) source paths, so the
 *  operator has a shape to edit rather than a blank object. */
function buildSkeleton(rows: AutocountMappingWriteRow[]): string {
  const obj: Record<string, string> = {};
  for (const r of rows) {
    if (r.sourcePath && !r.sourcePath.includes('.')) obj[r.sourcePath] = '';
  }
  return JSON.stringify(obj, null, 2);
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'string') return value === '' ? '""' : value;
  return String(value);
}

function FieldResultRow({ field }: { field: AutocountSimulateFieldResult }) {
  return (
    <tr className="border-b align-top last:border-0">
      <td className="px-2 py-1.5">
        <span className="font-medium">{humanizeFieldKey(field.canonicalField)}</span>
      </td>
      <td className="px-2 py-1.5">
        <code className="text-xs text-muted-foreground">{field.sourcePath}</code>
      </td>
      <td className="px-2 py-1.5">
        {field.ok ? (
          <code className="text-xs">{renderValue(field.value)}</code>
        ) : (
          <span className="text-xs font-medium text-destructive">{field.error}</span>
        )}
      </td>
    </tr>
  );
}

export function MappingSimulator({
  open,
  onOpenChange,
  rows,
  onSimulate,
  entityLabel,
}: MappingSimulatorProps) {
  const [recordText, setRecordText] = useState('');
  const [result, setResult] = useState<AutocountSimulateResult | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setRecordText(buildSkeleton(rows));
      setResult(null);
      setRunError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const parsed = useMemo<
    { ok: true; record: Record<string, unknown> } | { ok: false; error: string }
  >(() => {
    if (recordText.trim() === '') return { ok: false, error: 'Enter a mock AutoCount record.' };
    try {
      const value = JSON.parse(recordText);
      if (value === null || typeof value !== 'object' || Array.isArray(value)) {
        return { ok: false, error: 'The record must be a JSON object.' };
      }
      return { ok: true, record: value as Record<string, unknown> };
    } catch {
      return { ok: false, error: 'That is not valid JSON.' };
    }
  }, [recordText]);

  const run = async () => {
    if (!parsed.ok) return;
    setRunning(true);
    setRunError(null);
    try {
      const res = await onSimulate(parsed.record, rows);
      setResult(res);
    } catch {
      setRunError('The simulation could not be run.');
      setResult(null);
    } finally {
      setRunning(false);
    }
  };

  const outputJson = result?.record ? JSON.stringify(result.record, null, 2) : null;
  const failedFields = result
    ? [...result.headerFields, ...result.lineFields.flat()].filter((f) => !f.ok)
    : [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Simulate mapping
            {entityLabel && (
              <Badge variant="secondary" appearance="light" size="sm">
                {entityLabel}
              </Badge>
            )}
          </DialogTitle>
        </DialogHeader>

        <DialogBody className="flex flex-col gap-4">
          <p className="text-xs text-muted-foreground">
            Transforms a mock record through the current mapping and writes nothing -
            a preview of what a real sync would produce, not a Sorento push.
          </p>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="flex flex-col gap-2">
              <span className="text-xs font-medium text-muted-foreground">
                AutoCount record (in)
              </span>
              <Textarea
                variant="sm"
                className="min-h-48 font-mono"
                aria-label="Mock AutoCount record"
                value={recordText}
                onChange={(e) => setRecordText(e.target.value)}
              />
              {!parsed.ok && recordText.trim() !== '' && (
                <p className="text-xs text-destructive" data-testid="record-parse-error">
                  {parsed.error}
                </p>
              )}
            </div>

            <div className="flex flex-col gap-2">
              <span className="text-xs font-medium text-muted-foreground">
                Sorento record (out)
              </span>
              <div
                className="min-h-48 overflow-auto rounded-md border border-border bg-muted/30 p-3"
                data-testid="sorento-output"
              >
                {result === null ? (
                  <p className="text-xs text-muted-foreground">Run to see the result.</p>
                ) : outputJson ? (
                  <pre className="whitespace-pre-wrap break-words font-mono text-xs">
                    {outputJson}
                  </pre>
                ) : (
                  <div className="flex items-center gap-1.5 text-xs font-medium text-destructive">
                    <TriangleAlert className="size-4" /> This record would be rejected.
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Button type="button" onClick={run} disabled={!parsed.ok || running}>
              {running ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : (
                <Play className="size-4" />
              )}
              Run simulation
            </Button>
            {runError && <span className="text-xs text-destructive">{runError}</span>}
          </div>

          {result && (
            <div className="flex flex-col gap-3">
              {failedFields.length > 0 && (
                <Alert variant="destructive" appearance="light">
                  <AlertIcon>
                    <TriangleAlert />
                  </AlertIcon>
                  <AlertTitle>
                    {failedFields.length} field{failedFields.length === 1 ? '' : 's'} failed
                  </AlertTitle>
                  <AlertDescription>
                    A real sync of this record would reject on these fields.
                  </AlertDescription>
                </Alert>
              )}

              <div className="overflow-x-auto">
                <table className="w-full min-w-[420px] text-sm" data-testid="field-results">
                  <thead>
                    <tr className="border-b text-start text-xs font-medium text-muted-foreground">
                      <th className="px-2 py-1.5 text-start font-medium">Sorento field</th>
                      <th className="px-2 py-1.5 text-start font-medium">Source</th>
                      <th className="px-2 py-1.5 text-start font-medium">Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.headerFields.map((f) => (
                      <FieldResultRow key={`h-${f.canonicalField}-${f.sourcePath}`} field={f} />
                    ))}
                    {result.lineFields.map((line, li) =>
                      line.map((f) => (
                        <FieldResultRow
                          key={`l-${li}-${f.canonicalField}-${f.sourcePath}`}
                          field={f}
                        />
                      )),
                    )}
                  </tbody>
                </table>
              </div>
              <div
                className={cn(
                  'flex items-center gap-1.5 text-xs',
                  result.ok ? 'text-success' : 'text-destructive',
                )}
              >
                <ArrowRight className="size-3.5" />
                {result.ok
                  ? 'This record maps cleanly.'
                  : 'This record would not be delivered as-is.'}
              </div>
            </div>
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
