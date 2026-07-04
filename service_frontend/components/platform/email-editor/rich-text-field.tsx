'use client';

import { useEffect, useRef } from 'react';
import { Bold, Italic, Link2, List, ListOrdered, Underline } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { TemplateContextFact } from '@/types/templates';

/**
 * WYSIWYG rich-text field for Text blocks (plan sprint-2/07). A toolbar drives
 * formatting via execCommand so the user NEVER types raw tags — that produced
 * literal, escaped `&lt;i&gt;` in the output. The command set is deliberately
 * limited to the email-safe vocabulary nh3 keeps server-side (b/i/u/a/ul/ol).
 *
 * Single writer: React never re-applies innerHTML while focused (the
 * contentEditable race we already fixed once) — the sync effect seeds it, the
 * user owns it after, commit fires on blur + after each command.
 */

export interface RichTextFieldProps {
  value: string;
  onChange: (html: string) => void;
  fields: TemplateContextFact[];
  disabled?: boolean;
  'aria-label'?: string;
}

function exec(command: string, arg?: string) {
  // execCommand is deprecated but the only zero-dep way to get exactly our
  // email-safe tag set (b/i/u/a/ul/ol); works in every current browser.
  document.execCommand(command, false, arg);
}

export function RichTextField({
  value,
  onChange,
  fields,
  disabled,
  'aria-label': ariaLabel,
}: RichTextFieldProps) {
  const ref = useRef<HTMLDivElement>(null);
  const savedRange = useRef<Range | null>(null);

  // Seed / re-seed only when the external value diverges and we're not editing.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (el.innerHTML !== value && document.activeElement !== el) {
      el.innerHTML = value;
    }
  }, [value]);

  const commit = () => {
    const el = ref.current;
    if (el) onChange(el.innerHTML);
  };

  // Remember the caret so a chip/link click (which steals focus) can restore it.
  const rememberSelection = () => {
    const sel = window.getSelection();
    if (sel && sel.rangeCount && ref.current?.contains(sel.anchorNode)) {
      savedRange.current = sel.getRangeAt(0).cloneRange();
    }
  };

  const withCaret = (fn: () => void) => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    const sel = window.getSelection();
    if (savedRange.current && sel) {
      sel.removeAllRanges();
      sel.addRange(savedRange.current);
    }
    fn();
    commit();
  };

  const applyLink = () => {
    const url = window.prompt('Link URL', 'https://');
    if (url) withCaret(() => exec('createLink', url));
  };

  const insertToken = (key: string) => {
    withCaret(() => exec('insertText', `{{${key}}}`));
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-0.5 rounded-md border border-input bg-muted/40 p-0.5">
        {(
          [
            { cmd: 'bold', icon: Bold, label: 'Bold' },
            { cmd: 'italic', icon: Italic, label: 'Italic' },
            { cmd: 'underline', icon: Underline, label: 'Underline' },
            { cmd: 'insertUnorderedList', icon: List, label: 'Bulleted list' },
            { cmd: 'insertOrderedList', icon: ListOrdered, label: 'Numbered list' },
          ] as const
        ).map(({ cmd, icon: Icon, label }) => (
          <Button
            key={cmd}
            type="button"
            variant="ghost"
            size="icon"
            className="size-7"
            aria-label={label}
            disabled={disabled}
            // mousedown (not click) so the editor keeps its selection.
            onMouseDown={(e) => {
              e.preventDefault();
              withCaret(() => exec(cmd));
            }}
          >
            <Icon className="size-3.5" />
          </Button>
        ))}
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-7"
          aria-label="Insert link"
          disabled={disabled}
          onMouseDown={(e) => {
            e.preventDefault();
            applyLink();
          }}
        >
          <Link2 className="size-3.5" />
        </Button>
      </div>

      <div
        ref={ref}
        role="textbox"
        aria-label={ariaLabel}
        data-testid="rich-text-editable"
        contentEditable={!disabled}
        suppressContentEditableWarning
        className="min-h-24 rounded-md border border-input bg-background px-3 py-2 text-sm leading-relaxed outline-none focus:ring-1 focus:ring-primary/60 [&_a]:text-primary [&_a]:underline [&_ol]:list-decimal [&_ol]:ps-5 [&_ul]:list-disc [&_ul]:ps-5"
        onInput={commit}
        onBlur={() => {
          rememberSelection();
          commit();
        }}
        onKeyUp={rememberSelection}
        onMouseUp={rememberSelection}
      />

      {fields.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          {fields.map((field) => (
            <Badge
              key={field.key}
              variant="secondary"
              data-testid={`merge-chip-${field.key}`}
              className={disabled ? 'opacity-50' : 'cursor-pointer hover:bg-accent'}
              onMouseDown={(e) => {
                e.preventDefault();
                if (!disabled) insertToken(field.key);
              }}
            >
              {field.label}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
