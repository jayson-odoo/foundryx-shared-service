'use client';

/**
 * Table field (sprint-3/02) - PO/SO/invoice line items. A real `<table>`:
 * authored columns, per-row **computed** columns (`qty * unit_price`, evaluated
 * over the row's own cells via the computed parser - never eval, anti-SSTI),
 * a column-total footer (`<tfoot>`, aligned under each column), optional row
 * numbers. Horizontal-scrolls on narrow screens so the columns never reflow.
 * Answer = `Record<string, FormAnswerScalar>[]`; per-row errors keyed
 * `key.rowIndex.colKey`. Computed cells are recomputed authoritatively server-
 * side on submit - the client value is display-only.
 */
import { Plus, Trash2 } from 'lucide-react';
import { SearchSelect } from '@/components/platform/search-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { evaluateExpression } from '@/lib/computed-expr';
import { cn } from '@/lib/utils';
import type { FormAnswerScalar, FormFieldErrors, FormSummarize, FormTableColumn } from '@/types/forms';

type Row = Record<string, FormAnswerScalar>;

export interface TableFieldProps {
  columns: FormTableColumn[];
  showRowNumbers?: boolean;
  minRows?: number;
  maxRows?: number;
  value: Row[];
  onChange: (rows: Row[]) => void;
  errors: FormFieldErrors;
  fieldKey: string;
  disabled?: boolean;
  idBase: string;
  /** Read-only submission view - inputs become text. */
  readOnly?: boolean;
}

const SUMMARIZE_CAPTION: Record<FormSummarize, string> = {
  sum: 'Total', avg: 'Average', count: 'Count', min: 'Minimum', max: 'Maximum',
};

function toNum(v: FormAnswerScalar): number {
  return typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN;
}

function fmtNum(n: number, decimals?: number): string {
  if (decimals != null && decimals >= 0) return n.toFixed(decimals);
  return Number.isInteger(n) ? String(n) : Number(n.toFixed(2)).toString();
}

/** Fill a row's derived cells (left-to-right, so a computed column can read an
 * earlier fixed/computed one). Returns a new row. */
function recompute(row: Row, columns: FormTableColumn[]): Row {
  const next = { ...row };
  for (const col of columns) {
    if (col.type === 'fixed') next[col.key] = col.fixedValue ?? '';
    else if (col.type === 'computed') {
      const result = evaluateExpression(col.computed?.expression ?? '', next);
      next[col.key] = result === null ? '' : result;
    }
  }
  return next;
}

function summarize(rows: Row[], col: FormTableColumn): string | null {
  if (!col.summarize) return null;
  if (col.summarize === 'count') return String(rows.length);
  const nums = rows.map((r) => toNum(r[col.key])).filter((n) => Number.isFinite(n));
  let v: number | null;
  if (col.summarize === 'sum') v = nums.reduce((a, b) => a + b, 0);
  else if (nums.length === 0) v = null;
  else if (col.summarize === 'avg') v = nums.reduce((a, b) => a + b, 0) / nums.length;
  else if (col.summarize === 'min') v = Math.min(...nums);
  else v = Math.max(...nums);
  return v === null ? '-' : fmtNum(v, col.decimals);
}

export function TableField({
  columns,
  showRowNumbers,
  minRows,
  maxRows,
  value,
  onChange,
  errors,
  fieldKey,
  disabled,
  idBase,
  readOnly,
}: TableFieldProps) {
  const rows = Array.isArray(value) ? value : [];
  const canAdd = maxRows == null || rows.length < maxRows;
  const canRemove = rows.length > (minRows ?? 0);
  const hasSummary = columns.some((c) => c.summarize);
  const editable = !disabled && !readOnly;

  const blankRow = (): Row => {
    const row: Row = {};
    for (const col of columns) if (col.type !== 'computed') row[col.key] = '';
    return recompute(row, columns);
  };

  const setCell = (rowIndex: number, colKey: string, cell: FormAnswerScalar) => {
    const next = rows.map((r, i) => (i === rowIndex ? recompute({ ...r, [colKey]: cell }, columns) : r));
    onChange(next);
  };

  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full min-w-max border-collapse text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/40 text-start">
            {showRowNumbers && <th className="w-10 px-3 py-2 text-start font-medium text-muted-foreground">#</th>}
            {columns.map((col) => (
              <th key={col.id} className="px-3 py-2 text-start font-medium text-foreground">
                {col.label}
                {col.required && <span className="text-destructive"> *</span>}
              </th>
            ))}
            {editable && <th className="w-12 px-3 py-2" />}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td
                colSpan={columns.length + (showRowNumbers ? 1 : 0) + (editable ? 1 : 0)}
                className="px-3 py-4 text-center text-muted-foreground"
              >
                No items yet.
              </td>
            </tr>
          )}
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="border-b border-border last:border-0 align-top">
              {showRowNumbers && (
                <td className="px-3 py-2 text-muted-foreground tabular-nums">{rowIndex + 1}</td>
              )}
              {columns.map((col) => {
                const errorKey = `${fieldKey}.${rowIndex}.${col.key}`;
                const error = errors[errorKey];
                return (
                  <td key={col.id} className="px-3 py-2">
                    <Cell
                      col={col}
                      id={`${idBase}-${rowIndex}-${col.key}`}
                      value={row[col.key]}
                      invalid={Boolean(error)}
                      readOnly={!editable}
                      onChange={(v) => setCell(rowIndex, col.key, v)}
                    />
                    {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
                  </td>
                );
              })}
              {editable && (
                <td className="px-3 py-2 text-center">
                  {canRemove && (
                    <button
                      type="button"
                      aria-label={`Remove row ${rowIndex + 1}`}
                      className="text-muted-foreground hover:text-destructive"
                      onClick={() => onChange(rows.filter((_, i) => i !== rowIndex))}
                    >
                      <Trash2 className="size-4" />
                    </button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
        {hasSummary && rows.length > 0 && (
          <tfoot>
            <tr className="border-t-2 border-border bg-muted/40 font-medium">
              {showRowNumbers && <td />}
              {columns.map((col) => {
                const total = summarize(rows, col);
                return (
                  <td key={col.id} className="px-3 py-2.5">
                    {total !== null && (
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="text-xs uppercase tracking-wide text-muted-foreground">
                          {SUMMARIZE_CAPTION[col.summarize as FormSummarize]}
                        </span>
                        <span className="text-base font-semibold tabular-nums text-foreground">{total}</span>
                      </div>
                    )}
                  </td>
                );
              })}
              {editable && <td />}
            </tr>
          </tfoot>
        )}
      </table>

      {editable && (
        <div className="border-t border-border p-2">
          <Button type="button" variant="outline" size="sm" onClick={() => onChange([...rows, blankRow()])} disabled={!canAdd}>
            <Plus className="size-4" />
            Add item
          </Button>
        </div>
      )}
    </div>
  );
}

interface CellProps {
  col: FormTableColumn;
  id: string;
  value: FormAnswerScalar;
  onChange: (value: FormAnswerScalar) => void;
  invalid?: boolean;
  readOnly?: boolean;
}

function Cell({ col, id, value, onChange, invalid, readOnly }: CellProps) {
  if (col.type === 'computed') {
    const n = toNum(value);
    const display = Number.isFinite(n) ? fmtNum(n, col.decimals) : '-';
    return (
      <span className="inline-block min-w-16 tabular-nums" data-slot="table-computed">
        {display}
      </span>
    );
  }
  if (col.type === 'fixed') {
    // Read-only constant - same for every row, server-stamped on submit.
    return (
      <span className="inline-block tabular-nums text-muted-foreground" data-slot="table-fixed">
        {col.fixedValue ?? '-'}
      </span>
    );
  }
  if (readOnly) {
    return <span className="text-foreground">{value === '' || value == null ? '-' : String(value)}</span>;
  }
  const common = { id, 'aria-invalid': invalid || undefined, className: cn('h-9', invalid && 'aria-invalid') };
  const isInt = col.type === 'integer' || col.integer;
  switch (col.type) {
    case 'number':
    case 'integer':
      return (
        <Input
          {...common}
          type="number"
          inputMode={isInt ? 'numeric' : 'decimal'}
          step={isInt ? '1' : col.decimals != null && col.decimals >= 0 ? String(10 ** -col.decimals) : undefined}
          value={value === null || value === undefined ? '' : String(value)}
          placeholder={col.placeholder}
          onKeyDown={(e) => {
            if (isInt && ['.', ',', 'e', 'E'].includes(e.key)) e.preventDefault();
          }}
          onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
          onBlur={(e) => {
            const dp = col.decimals;
            if (isInt || dp == null || dp < 0 || e.target.value === '') return;
            const n = Number(e.target.value);
            if (Number.isFinite(n)) onChange(n.toFixed(dp));
          }}
        />
      );
    case 'date':
      return <Input {...common} type="date" value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} />;
    case 'select':
      return (
        <SearchSelect
          options={(col.options?.items ?? []).map((o) => ({ value: o.value, label: o.label }))}
          value={value == null ? null : String(value)}
          ariaLabel={col.label}
          onChange={(v) => onChange(v)}
        />
      );
    default:
      return (
        <Input
          {...common}
          type="text"
          value={String(value ?? '')}
          placeholder={col.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      );
  }
}
