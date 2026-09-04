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

/** One insertable named variable (sprint-5/02, AC-02-20) - `token` is what
 *  lands in the formula text at the caret, `label` is the button/list text. */
export interface FormulaVariableItem {
  label: string;
  token: string;
}

/** A grouped section of the Variables panel (e.g. "Header columns", "Line
 *  aggregates"). */
export interface FormulaVariableGroup {
  label: string;
  items: FormulaVariableItem[];
}

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
  /**
   * A document header/line row's named-variable universe (sprint-5/02,
   * AC-02-20): header/line columns and, for a header row, the `lines.*`
   * aggregates. Present ⇒ the dialog renders a searchable Variables panel
   * (insert-at-caret) AND widens live validation to accept these names -
   * ABSENT (the default) leaves the master-entity single-`value` model
   * untouched. Testing (single-`value` sample) is hidden while variables are
   * offered - a multi-variable formula has no single sample to test against.
   */
  variables?: FormulaVariableGroup[];
  /** Literal string chips (e.g. the `status` target's fixed vocabulary) -
   *  inserted quoted, never counted as a variable name. */
  literalOptions?: FormulaVariableItem[];
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
  variables,
  literalOptions,
}: AutocountFormulaBuilderProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [draft, setDraft] = useState(value);
  const [tab, setTab] = useState('formula');
  const [category, setCategory] = useState<string>(initialCategory);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<FunctionDef | null>(null);
  const [variableSearch, setVariableSearch] = useState('');

  const hasVariables = Boolean(variables && variables.length > 0);

  // Reset the working draft each time the dialog is opened from the row's value.
  useEffect(() => {
    if (open) {
      setDraft(value);
      setTab('formula');
      setCategory(initialCategory);
      setSearch('');
      setSelected(null);
      setVariableSearch('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const knownVariableTokens = useMemo(
    () => (variables ?? []).flatMap((g) => g.items.map((i) => i.token)),
    [variables],
  );
  const error = useMemo(
    () => (draft.trim() === '' ? null : validateFormula(draft, knownVariableTokens)),
    [draft, knownVariableTokens],
  );
  const canApply = draft.trim() === '' || error === null;

  // Literal chips (e.g. the `status` vocabulary) render as their OWN group in
  // the same panel, but never count toward the known-variable set (they
  // insert as quoted string literals, not identifiers).
  const variablePanelGroups = useMemo(() => {
    const groups = variables ? [...variables] : [];
    if (literalOptions && literalOptions.length > 0) {
      groups.push({ label: 'Status', items: literalOptions });
    }
    return groups;
  }, [variables, literalOptions]);

  const filteredVariableGroups = useMemo(() => {
    const q = variableSearch.trim().toLowerCase();
    if (!q) return variablePanelGroups;
    return variablePanelGroups
      .map((g) => ({
        ...g,
        items: g.items.filter(
          (i) => i.label.toLowerCase().includes(q) || i.token.toLowerCase().includes(q),
        ),
      }))
      .filter((g) => g.items.length > 0);
  }, [variablePanelGroups, variableSearch]);

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
      <DialogContent className={hasVariables ? 'max-w-4xl' : 'max-w-2xl'}>
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
            {/* A multi-variable (document header/line) formula has no single
                sample `value` to test against - the Testing tab only makes
                sense for the master-entity model (foolproof-UI: don't offer
                a control that can't work). */}
            {!hasVariables && (
              <TabsList className="mb-3">
                <TabsTrigger value="formula">Formula</TabsTrigger>
                <TabsTrigger value="testing">Testing</TabsTrigger>
              </TabsList>
            )}

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
                  className="h-8 rounded-md border border-border bg-primary/10 px-2.5 font-mono text-xs text-primary hover:bg-primary/20"
                  onClick={() => insert('value')}
                >
                  value
                </button>
                {OPERATOR_CATALOG.map((op) => (
                  <button
                    key={op.symbol}
                    type="button"
                    title={op.description}
                    className="h-8 min-w-8 rounded-md border border-border bg-muted/40 px-2 font-mono text-xs hover:bg-accent"
                    onClick={() => insert(` ${op.symbol} `)}
                  >
                    {op.symbol}
                  </button>
                ))}
                <button
                  type="button"
                  aria-label="Backspace"
                  className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-muted/40 hover:bg-accent"
                  onClick={backspace}
                >
                  <Delete className="size-4" />
                </button>
              </div>

              <div
                className={cn(
                  'grid grid-cols-1 gap-3',
                  hasVariables ? 'lg:grid-cols-3' : 'sm:grid-cols-2',
                )}
              >
                {/* Variables panel (sprint-5/02, AC-02-20) - a document row's
                    header/line columns + line aggregates, searchable +
                    insert-at-caret, same shape as the function catalog. */}
                {hasVariables && (
                  <div className="flex flex-col gap-2">
                    <div className="relative">
                      <Search className="absolute start-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                      <Input
                        className="h-9 ps-8 text-xs"
                        aria-label="Search variables"
                        placeholder="Search variables…"
                        value={variableSearch}
                        onChange={(e) => setVariableSearch(e.target.value)}
                      />
                    </div>
                    <div className="max-h-52 overflow-y-auto rounded-md border border-border">
                      {filteredVariableGroups.length === 0 ? (
                        <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                          No variables.
                        </p>
                      ) : (
                        filteredVariableGroups.map((group) => (
                          <div key={group.label}>
                            <p className="border-b border-border bg-muted/30 px-3 py-1 text-[11px] font-medium text-muted-foreground">
                              {group.label}
                            </p>
                            {group.items.map((item) => (
                              <button
                                key={item.token}
                                type="button"
                                className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-start hover:bg-accent"
                                onClick={() => insert(item.token)}
                              >
                                <span className="truncate text-xs">{item.label}</span>
                                <code className="shrink-0 font-mono text-[11px] text-muted-foreground">
                                  {item.token}
                                </code>
                              </button>
                            ))}
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                )}

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

            {!hasVariables && (
              <TabsContent value="testing">
                <FormulaTesting formula={draft} onServerTest={onServerTest} />
              </TabsContent>
            )}
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
