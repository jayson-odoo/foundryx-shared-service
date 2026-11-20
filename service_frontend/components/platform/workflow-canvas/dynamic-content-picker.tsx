'use client';

/**
 * Dynamic-content field (plan sprint-2/08 D7) - n8n-style. A text/textarea
 * input plus a picker that lists every upstream node's declared output schema,
 * grouped by source; choosing one inserts the correct `{{ ref }}` at the caret.
 * Flat run-context underneath, typed picker on top.
 */
import { useRef } from 'react';
import { Braces } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { cn } from '@/lib/utils';
import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Textarea } from '@/components/ui/textarea';

export interface DynamicContentGroup {
  /** Source node's unique display name, e.g. "Send email 2". */
  sourceLabel: string;
  /** Distance hint, e.g. "1 node back" (n8n) - disambiguates same-type nodes. */
  hint?: string;
  items: { key: string; label: string }[];
}

export interface DynamicContentFieldProps {
  value: string;
  onChange: (value: string) => void;
  groups: DynamicContentGroup[];
  multiline?: boolean;
  /** Textarea height when multiline (default 3). */
  rows?: number;
  placeholder?: string;
  disabled?: boolean;
  'aria-label'?: string;
}

function insertAtCaret(
  el: HTMLInputElement | HTMLTextAreaElement | null,
  value: string,
  ref: string,
  onChange: (next: string) => void,
): void {
  const token = `{{ ${ref} }}`;
  const hasCaret = el != null && document.activeElement === el;
  const start = hasCaret ? (el.selectionStart ?? value.length) : value.length;
  const end = hasCaret ? (el.selectionEnd ?? value.length) : value.length;
  onChange(value.slice(0, start) + token + value.slice(end));
  requestAnimationFrame(() => {
    el?.focus();
    const caret = start + token.length;
    el?.setSelectionRange(caret, caret);
  });
}

export function DynamicContentField({
  value,
  onChange,
  groups,
  multiline = false,
  rows = 3,
  placeholder,
  disabled,
  'aria-label': ariaLabel,
}: DynamicContentFieldProps) {
  const ref = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null);
  const hasContent = groups.some((g) => g.items.length > 0);

  return (
    <div className="flex items-start gap-1.5">
      {multiline ? (
        <Textarea
          ref={ref as React.RefObject<HTMLTextAreaElement>}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          rows={rows}
          aria-label={ariaLabel}
          className="flex-1"
        />
      ) : (
        <Input
          ref={ref as React.RefObject<HTMLInputElement>}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          aria-label={ariaLabel}
          className="flex-1"
        />
      )}
      <Popover>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-9 shrink-0"
            disabled={disabled || !hasContent}
            aria-label="Insert dynamic content"
            data-testid="dynamic-content-trigger"
          >
            <Braces className="size-4" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-72 p-0">
          <div className="border-b px-3 py-2 text-xs font-semibold text-foreground">
            Dynamic content
          </div>
          <div className="max-h-72 overflow-y-auto overscroll-contain">
            <div className="p-1.5">
              {groups.map((group) => (
                <div key={group.sourceLabel} className="mb-1.5">
                  <div className="flex items-baseline justify-between gap-2 px-2 py-1">
                    <span className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">
                      {group.sourceLabel}
                    </span>
                    {group.hint && (
                      <span className="text-2xs font-normal lowercase text-muted-foreground/70">
                        {group.hint}
                      </span>
                    )}
                  </div>
                  {group.items.map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      data-testid={`dynamic-content-${item.key}`}
                      onClick={() => insertAtCaret(ref.current, value, item.key, onChange)}
                      className={cn(PRESSED_CLASS, 'flex w-full flex-col items-start rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent')}
                    >
                      <span className="text-foreground">{item.label}</span>
                      <span className="font-mono text-2xs text-muted-foreground">
                        {`{{ ${item.key} }}`}
                      </span>
                    </button>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
