'use client';

/**
 * Reusable formula-builder popup (sprint-3/02 follow-up). A SHELL: initialise it
 * with the supported variables + operators; the operator buttons + variable list
 * insert tokens at the caret, and a `validate` callback gives live feedback.
 * Used by the computed FIELD and the table computed COLUMN - the host owns the
 * variable list + the semantic validation, so the builder stays generic.
 *
 * Anti-SSTI: this only EDITS an expression string; evaluation stays in the
 * arithmetic-only `computed-expr` parser. No eval anywhere.
 */
import { useMemo, useRef, useState } from 'react';
import { Check, Delete, X } from 'lucide-react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

export interface FormulaVariable {
  label: string;
  token: string;
}

export interface FormulaBuilderProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  value: string;
  onChange: (expr: string) => void;
  variables: FormulaVariable[];
  /** Display labels → inserted symbols. Defaults to + − × ÷ ( ). */
  operators?: { label: string; insert: string }[];
  /** Host semantic check - return an error string or null when valid. */
  validate?: (expr: string) => string | null;
  title?: string;
}

const DEFAULT_OPERATORS = [
  { label: '+', insert: '+' },
  { label: '−', insert: '-' },
  { label: '×', insert: '*' },
  { label: '÷', insert: '/' },
  { label: '(', insert: '(' },
  { label: ')', insert: ')' },
];

export function FormulaBuilder({
  open,
  onOpenChange,
  value,
  onChange,
  variables,
  operators = DEFAULT_OPERATORS,
  validate,
  title = 'Build formula',
}: FormulaBuilderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [search, setSearch] = useState('');

  const error = useMemo(() => (validate ? validate(value) : null), [validate, value]);
  const valid = !error && value.trim().length > 0;

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return variables;
    return variables.filter((v) => v.label.toLowerCase().includes(q) || v.token.toLowerCase().includes(q));
  }, [variables, search]);

  /** Insert `text` at the caret (wrapping in surrounding spaces for operators so
   * `a*b` reads as `a * b`), keeping focus + caret after it. */
  const insert = (text: string, spaced = false) => {
    const el = inputRef.current;
    const start = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? value.length;
    const chunk = spaced ? ` ${text} ` : text;
    const next = value.slice(0, start) + chunk + value.slice(end);
    onChange(next);
    requestAnimationFrame(() => {
      el?.focus();
      const pos = start + chunk.length;
      el?.setSelectionRange(pos, pos);
    });
  };

  const backspace = () => {
    const el = inputRef.current;
    const start = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? value.length;
    if (start === end && start === 0) return;
    const from = start === end ? start - 1 : start;
    const next = value.slice(0, from) + value.slice(end);
    onChange(next);
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(from, from);
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-3">
          <Input
            ref={inputRef}
            className="font-mono text-sm"
            aria-label="Formula expression"
            placeholder="qty * unit_price"
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />

          <div className="flex flex-wrap gap-1.5">
            {operators.map((op) => (
              <button
                key={op.label}
                type="button"
                className="h-9 w-9 rounded-md border border-border bg-muted/40 font-mono text-base hover:bg-accent"
                onClick={() => insert(op.insert, op.insert !== '(' && op.insert !== ')')}
              >
                {op.label}
              </button>
            ))}
            <button
              type="button"
              aria-label="Backspace"
              className="flex h-9 w-9 items-center justify-center rounded-md border border-border bg-muted/40 hover:bg-accent"
              onClick={backspace}
            >
              <Delete className="size-4" />
            </button>
            <button
              type="button"
              className="h-9 rounded-md border border-border bg-muted/40 px-3 text-xs hover:bg-accent"
              onClick={() => onChange('')}
            >
              Clear
            </button>
          </div>

          <div className="flex flex-col gap-1.5">
            <Input
              className="h-8 text-xs"
              aria-label="Search variables"
              placeholder="Search variables…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <div className="max-h-44 overflow-y-auto rounded-md border border-border">
              {filtered.length === 0 ? (
                <p className="px-3 py-6 text-center text-xs text-muted-foreground">No variables.</p>
              ) : (
                filtered.map((v) => (
                  <button
                    key={v.token}
                    type="button"
                    className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-start text-sm hover:bg-accent"
                    title={v.token}
                    onClick={() => insert(v.token)}
                  >
                    <span className="truncate">{v.label}</span>
                    <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{v.token}</span>
                  </button>
                ))
              )}
            </div>
          </div>

          <div
            className={cn(
              'flex items-center gap-1.5 text-xs',
              error ? 'text-destructive' : valid ? 'text-success' : 'text-muted-foreground',
            )}
            data-testid="formula-status"
          >
            {error ? (
              <>
                <X className="size-3.5" /> {error}
              </>
            ) : valid ? (
              <>
                <Check className="size-3.5" /> Valid formula
              </>
            ) : (
              'Build an expression using the operators and variables above.'
            )}
          </div>
        </DialogBody>
        <DialogFooter>
          <Button type="button" onClick={() => onOpenChange(false)}>
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
