'use client';

/**
 * Merge-field builder dialog - same shell idiom as the form engine's
 * `FormulaBuilder` (searchable variable list + an expression input + live
 * status), but for `{{ token }}` insertion rather than arithmetic. The
 * variable list is SEARCHABLE (scales to any context vocabulary - replaces the
 * old always-on chip wall, which grew unbounded). A preview line renders the
 * value with the context's sample facts so the merged result is visible.
 *
 * Anti-SSTI: only edits a string + inserts `{{key}}` tokens. Substitution-only.
 */
import { useMemo, useRef, useState } from 'react';
import { Braces } from 'lucide-react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { TemplateContextFact } from '@/types/templates';

const TOKEN_RE = /\{\{\s*([\w.]+)\s*\}\}/g;

function renderWithSamples(value: string, fields: TemplateContextFact[]): string {
  const samples = new Map(fields.map((f) => [f.key, f.sample]));
  return value.replace(TOKEN_RE, (_, key: string) => samples.get(key) ?? '');
}

export interface MergeFieldBuilderProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  value: string;
  onChange: (value: string) => void;
  fields: TemplateContextFact[];
  multiline?: boolean;
  title?: string;
}

export function MergeFieldBuilder({
  open,
  onOpenChange,
  value,
  onChange,
  fields,
  multiline = false,
  title = 'Insert field',
}: MergeFieldBuilderProps) {
  const inputRef = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return fields;
    return fields.filter(
      (f) => f.label.toLowerCase().includes(q) || f.key.toLowerCase().includes(q),
    );
  }, [fields, search]);

  /** Insert {{key}} at the caret, keeping focus + caret after it. */
  const insert = (key: string) => {
    const token = `{{${key}}}`;
    const el = inputRef.current;
    const hasCaret = el != null && document.activeElement === el;
    const start = hasCaret ? (el.selectionStart ?? value.length) : value.length;
    const end = hasCaret ? (el.selectionEnd ?? value.length) : value.length;
    onChange(value.slice(0, start) + token + value.slice(end));
    requestAnimationFrame(() => {
      el?.focus();
      const caret = start + token.length;
      el?.setSelectionRange(caret, caret);
    });
  };

  const preview = renderWithSamples(value, fields);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className="sr-only">
            Insert merge fields into this value.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-3">
          {multiline ? (
            <Textarea
              ref={inputRef}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              rows={4}
              aria-label="Field value"
              placeholder="Type text and insert fields…"
            />
          ) : (
            <Input
              ref={inputRef}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              aria-label="Field value"
              placeholder="Type text and insert fields…"
            />
          )}

          <div className="flex flex-col gap-1.5">
            <Input
              className="h-8 text-xs"
              aria-label="Search fields"
              placeholder="Search fields…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <div className="max-h-44 overflow-y-auto rounded-md border border-border">
              {filtered.length === 0 ? (
                <p className="px-3 py-6 text-center text-xs text-muted-foreground">No fields.</p>
              ) : (
                filtered.map((field) => (
                  <button
                    key={field.key}
                    type="button"
                    data-testid={`merge-chip-${field.key}`}
                    title={`{{${field.key}}}`}
                    className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-start text-sm hover:bg-accent"
                    onClick={() => insert(field.key)}
                  >
                    <span className="truncate">{field.label}</span>
                    <span className="shrink-0 font-mono text-2xs text-muted-foreground">
                      {`{{${field.key}}}`}
                    </span>
                  </button>
                ))
              )}
            </div>
          </div>

          <div className="flex items-start gap-1.5 text-xs text-muted-foreground">
            <Braces className="mt-0.5 size-3.5 shrink-0" />
            <span>
              Preview: <span className="text-foreground">{preview || '-'}</span>
            </span>
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
