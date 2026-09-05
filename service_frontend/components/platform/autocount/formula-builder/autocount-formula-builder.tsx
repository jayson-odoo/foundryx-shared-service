'use client';

/**
 * The AutoCount transform formula builder (AC-16-11..15) - a Qrvey-style dialog
 * over the SAFE mirrored engine (`lib/autocount-formula.ts`). It only EDITS an
 * expression string; evaluation/validation stay in the hand-written parser (no
 * eval anywhere). Two tabs:
 *   • Formula - a textarea with live parse validation, an insert-at-caret
 *     function catalog grouped by data type + searchable, a per-function
 *     reference panel, and the structured date-format tool.
 *   • Testing - a mock value in → live output + a server parity check.
 *
 * Read-only-until-Edit is enforced by the caller (the Build affordance only
 * renders under the mapping form's global Edit toggle); a formula that fails to
 * parse cannot be applied (front gate; the PUT 422 is the backstop).
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, Delete, FunctionSquare, Info, Search, X } from 'lucide-react';
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
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { SearchSelect } from '@/components/platform/search-select';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import {
  FUNCTION_CATALOG,
  OPERATOR_CATALOG,
  validateFormula,
  type FunctionDef,
} from '@/lib/autocount-formula';
import { cn } from '@/lib/utils';
import type { AutocountFormulaTestResult } from '@/types/autocount';
import { DateFormatTool } from './date-format-tool';
import { FormulaTesting } from './formula-testing';

const CATEGORIES = ['All', 'String', 'Number', 'Boolean', 'Date', 'Logical'] as const;
const CATEGORY_OPTIONS = CATEGORIES.map((c) => ({ value: c, label: c }));

export interface AutocountFormulaBuilderProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The formula being edited (may be empty). */
  value: string;
  /** Commit the edited formula to the row (empty ⇒ the caller falls back to the
   *  named transform). */
  onApply: (formula: string) => void;
  /** Server-authoritative single-formula eval for the Testing tab's parity check. */
  onServerTest: (formula: string, value: unknown) => Promise<AutocountFormulaTestResult>;
  /** The Sorento field this row feeds - shown as context in the header. */
  fieldLabel?: string;
  /** Open on the Date category (a Date-preset row). */
  initialCategory?: string;
  /** A concise caveat shown under the formats line (e.g. the Decimal precision
   *  note) - a contextual statement, not procedural how-to copy. */
  note?: string;
}

export function AutocountFormulaBuilder({
  open,
  onOpenChange,
  value,
  onApply,
  onServerTest,
  fieldLabel,
  initialCategory = 'All',
  note,
}: AutocountFormulaBuilderProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [draft, setDraft] = useState(value);
  const [tab, setTab] = useState('formula');
  const [category, setCategory] = useState<string>(initialCategory);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<FunctionDef | null>(null);

  // Reset the working draft each time the dialog is opened from the row's value.
  useEffect(() => {
    if (open) {
      setDraft(value);
      setTab('formula');
      setCategory(initialCategory);
      setSearch('');
      setSelected(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const error = useMemo(
    () => (draft.trim() === '' ? null : validateFormula(draft)),
    [draft],
  );
  const canApply = draft.trim() === '' || error === null;

  const functions = useMemo(() => {
    const q = search.trim().toLowerCase();
    return FUNCTION_CATALOG.filter((f) => {
      if (category !== 'All' && f.category !== category) return false;
      if (!q) return true;
      return f.name.toLowerCase().includes(q) || f.description.toLowerCase().includes(q);
    });
  }, [category, search]);

  /** Insert `text` at the caret; `caretOffset` (from the inserted chunk's end)
   *  lets a `fn()` insert land the caret between the parentheses. */
  const insert = (text: string, caretOffset = 0) => {
    const el = textareaRef.current;
    const start = el?.selectionStart ?? draft.length;
    const end = el?.selectionEnd ?? draft.length;
    const next = draft.slice(0, start) + text + draft.slice(end);
    setDraft(next);
    requestAnimationFrame(() => {
      el?.focus();
      const pos = start + text.length - caretOffset;
      el?.setSelectionRange(pos, pos);
    });
  };

  const insertFunction = (fn: FunctionDef) => {
    setSelected(fn);
    // Land the caret inside the parentheses so the first argument is next.
    insert(`${fn.name}()`, 1);
  };

  const backspace = () => {
    const el = textareaRef.current;
    const start = el?.selectionStart ?? draft.length;
    const end = el?.selectionEnd ?? draft.length;
    if (start === end && start === 0) return;
    const from = start === end ? start - 1 : start;
    setDraft(draft.slice(0, from) + draft.slice(end));
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(from, from);
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FunctionSquare className="size-4" />
            Transform formula
            {fieldLabel && (
              <Badge variant="secondary" appearance="light" size="sm">
                {fieldLabel}
              </Badge>
            )}
          </DialogTitle>
        </DialogHeader>

        <DialogBody>
          <Tabs value={tab} onValueChange={setTab}>
            {/* Segmented mode switch, not content navigation (AC-DLA-12) -
                pinned explicitly, the tab strip default is now `line`. */}
            <TabsList className="mb-3" variant="default">
              <TabsTrigger value="formula">Formula</TabsTrigger>
              <TabsTrigger value="testing">Testing</TabsTrigger>
            </TabsList>

            <TabsContent value="formula" className="flex flex-col gap-3">
              {/* Accepted-formats reference (AC-16-15) - a concise statement, not
                  procedural how-to copy. */}
              <p className="text-xs text-muted-foreground">
                Values arrive as text (e.g. <code>&quot;T&quot;</code>,{' '}
                <code>&quot;30000.0&quot;</code>). Dates use tokens like{' '}
                <code>yyyy/MM/dd HH:mm:ss</code>. Join text with <code>&amp;</code>;{' '}
                <code>+</code> is numeric only.
              </p>

              {note && (
                <p
                  className="flex items-start gap-1.5 text-xs text-warning"
                  data-testid="formula-note"
                >
                  <Info className="mt-0.5 size-3.5 shrink-0" /> {note}
                </p>
              )}

              <Textarea
                ref={textareaRef}
                variant="sm"
                className="min-h-24 font-mono"
                aria-label="Formula expression"
                placeholder='if(value == "T", true, false)'
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
              />

              <div
                className={cn(
                  'flex items-center gap-1.5 text-xs',
                  error ? 'text-destructive' : draft.trim() ? 'text-success' : 'text-muted-foreground',
                )}
                data-testid="formula-status"
              >
                {error ? (
                  <>
                    <X className="size-3.5" /> {error}
                  </>
                ) : draft.trim() ? (
                  <>
                    <Check className="size-3.5" /> Valid formula
                  </>
                ) : (
                  'Empty - this field falls back to its transform preset.'
                )}
              </div>

              {/* value variable + operator inserts */}
              <div className="flex flex-wrap gap-1.5">
                <button
                  type="button"
                  className={cn(
                    PRESSED_CLASS,
                    'h-8 rounded-md border border-border bg-primary/10 px-2.5 font-mono text-xs text-primary hover:bg-primary/20',
                  )}
                  onClick={() => insert('value')}
                >
                  value
                </button>
                {OPERATOR_CATALOG.map((op) => (
                  <button
                    key={op.symbol}
                    type="button"
                    title={op.description}
                    className={cn(
                      PRESSED_CLASS,
                      'h-8 min-w-8 rounded-md border border-border bg-muted/40 px-2 font-mono text-xs hover:bg-accent',
                    )}
                    onClick={() => insert(` ${op.symbol} `)}
                  >
                    {op.symbol}
                  </button>
                ))}
                <button
                  type="button"
                  aria-label="Backspace"
                  className={cn(
                    PRESSED_CLASS,
                    'flex h-8 w-8 items-center justify-center rounded-md border border-border bg-muted/40 hover:bg-accent',
                  )}
                  onClick={backspace}
                >
                  <Delete className="size-4" />
                </button>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {/* Function catalog - grouped by type + searchable (AC-16-13). */}
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-2">
                    <div className="w-28 shrink-0">
                      <SearchSelect
                        options={CATEGORY_OPTIONS}
                        value={category}
                        onChange={setCategory}
                        ariaLabel="Function category"
                      />
                    </div>
                    <div className="relative flex-1">
                      <Search className="absolute start-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                      <Input
                        className="h-9 ps-8 text-xs"
                        aria-label="Search functions"
                        placeholder="Search functions…"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                      />
                    </div>
                  </div>
                  <div className="max-h-52 overflow-y-auto rounded-md border border-border">
                    {functions.length === 0 ? (
                      <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                        No functions.
                      </p>
                    ) : (
                      functions.map((fn) => (
                        <button
                          key={fn.name}
                          type="button"
                          className={cn(
                            PRESSED_CLASS,
                            'flex w-full items-center justify-between gap-2 px-3 py-1.5 text-start hover:bg-accent',
                            selected?.name === fn.name && 'bg-accent',
                          )}
                          onClick={() => insertFunction(fn)}
                        >
                          <span className="truncate font-mono text-xs">{fn.signature}</span>
                          <Badge variant="secondary" appearance="light" size="sm">
                            {fn.category}
                          </Badge>
                        </button>
                      ))
                    )}
                  </div>
                </div>

                {/* Reference panel (AC-16-15) + the Date tool for Date work. */}
                <div className="flex flex-col gap-3">
                  {selected ? (
                    <div
                      className="flex flex-col gap-2 rounded-md border border-border p-3"
                      data-testid="function-reference"
                    >
                      <code className="font-mono text-xs font-semibold">{selected.signature}</code>
                      <p className="text-xs text-muted-foreground">{selected.description}</p>
                      <dl className="flex flex-col gap-1">
                        {selected.args.map((arg) => (
                          <div key={arg.name} className="flex gap-2 text-xs">
                            <dt className="shrink-0 font-mono font-medium">{arg.name}</dt>
                            <dd className="text-muted-foreground">{arg.description}</dd>
                          </div>
                        ))}
                      </dl>
                      <p className="text-xs">
                        <span className="text-muted-foreground">Example: </span>
                        <code className="font-mono">{selected.example}</code>
                      </p>
                    </div>
                  ) : (
                    <div className="flex items-center justify-center rounded-md border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
                      Select a function to see its reference.
                    </div>
                  )}

                  {category === 'Date' && <DateFormatTool onInsert={(f) => insert(f)} />}
                </div>
              </div>
            </TabsContent>

            <TabsContent value="testing">
              <FormulaTesting formula={draft} onServerTest={onServerTest} />
            </TabsContent>
          </Tabs>
        </DialogBody>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={!canApply}
            onClick={() => {
              onApply(draft.trim());
              onOpenChange(false);
            }}
          >
            Apply
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
