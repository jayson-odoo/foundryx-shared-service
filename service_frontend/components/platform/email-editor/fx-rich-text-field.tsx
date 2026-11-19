'use client';

/**
 * The rich text field with the Foundryx UIUX switch on (playbook 0.71.0
 * "Rich text fields"): one field box with a slim toolbar along its top edge,
 * icon buttons with tooltips, and the ones that apply where the caret is
 * tinted in `--fx-link-bg`. Only the look changes: the commands, the caret
 * handling, the merge-field insert and the commit are `useRichTextField`'s,
 * the same as the legacy look, so the HTML it emits is the same.
 *
 * Not taken from the playbook (they would change what is saved): typing
 * "- " to start a list, and dropping pasted formatting in the browser
 * (the server's sanitiser keeps doing that).
 */
import { useEffect, useState, type ComponentType, type SVGProps } from 'react';
import { Bold, Italic, Link2, List, ListOrdered, Underline } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { FxTooltip } from '@/components/fx/fx-tooltip';
import type { RichTextFieldProps } from './rich-text-field';
import { exec, useRichTextField } from './use-rich-text-field';

type Command = 'bold' | 'italic' | 'underline' | 'insertUnorderedList' | 'insertOrderedList';

const TOOLS: { cmd: Command; icon: ComponentType<SVGProps<SVGSVGElement>>; label: string; keys?: string }[] = [
  { cmd: 'bold', icon: Bold, label: 'Bold', keys: 'Ctrl+B' },
  { cmd: 'italic', icon: Italic, label: 'Italic', keys: 'Ctrl+I' },
  { cmd: 'underline', icon: Underline, label: 'Underline', keys: 'Ctrl+U' },
  { cmd: 'insertUnorderedList', icon: List, label: 'Bulleted list' },
  { cmd: 'insertOrderedList', icon: ListOrdered, label: 'Numbered list' },
];

const TOOL_CLASS =
  'size-8 rounded-(--fx-r-s) text-(--fx-ink-2) hover:bg-(--fx-surface-2) hover:text-(--fx-ink) aria-pressed:bg-(--fx-link-bg) aria-pressed:text-(--fx-link)';

/** Which of the toolbar's commands apply where the caret is (look only). */
function readActive(): Set<Command> {
  const on = new Set<Command>();
  if (typeof document.queryCommandState !== 'function') return on;
  for (const t of TOOLS) {
    try {
      if (document.queryCommandState(t.cmd)) on.add(t.cmd);
    } catch {
      // A browser without the command: shown as not applied.
    }
  }
  return on;
}

export function FxRichTextField({
  value,
  onChange,
  fields,
  disabled,
  'aria-label': ariaLabel,
}: RichTextFieldProps) {
  const { ref, commit, rememberSelection, withCaret, applyLink, insertToken } = useRichTextField(
    value,
    onChange,
  );
  const [active, setActive] = useState<Set<Command>>(() => new Set());

  // Re-read the tinted tools whenever the caret moves inside this field.
  useEffect(() => {
    const onSelection = () => {
      const el = ref.current;
      const sel = window.getSelection();
      if (!el || !sel || !sel.anchorNode || !el.contains(sel.anchorNode)) return;
      setActive(readActive());
    };
    document.addEventListener('selectionchange', onSelection);
    return () => document.removeEventListener('selectionchange', onSelection);
  }, [ref]);

  return (
    <div className="flex flex-col gap-1.5">
      <div
        data-fx-rich-text=""
        className={cn(
          'flex flex-col overflow-hidden rounded-(--fx-r-m) border border-(--fx-line) bg-(--fx-surface) transition-[border-color,box-shadow] duration-(--fx-t-hover) ease-(--fx-ease-out) focus-within:border-(--fx-link) focus-within:ring-2 focus-within:ring-(--fx-link)/25',
          disabled && 'opacity-60',
        )}
      >
        <div
          role="toolbar"
          aria-label={ariaLabel ? `${ariaLabel} formatting` : 'Formatting'}
          className="flex flex-wrap items-center gap-0.5 border-b border-(--fx-line) bg-(--fx-surface-2) px-1 py-0.5"
        >
          {TOOLS.map(({ cmd, icon: Icon, label, keys }) => (
            <FxTooltip key={cmd} label={keys ? `${label} (${keys})` : label}>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className={TOOL_CLASS}
                aria-label={label}
                aria-pressed={active.has(cmd)}
                disabled={disabled}
                // mousedown (not click) so the editor keeps its selection.
                onMouseDown={(e) => {
                  e.preventDefault();
                  withCaret(() => exec(cmd));
                  setActive(readActive());
                }}
                // Keyboard (Enter or Space on the focused tool): the same command.
                onClick={(e) => {
                  if (e.detail !== 0) return;
                  withCaret(() => exec(cmd));
                  setActive(readActive());
                }}
              >
                <Icon aria-hidden="true" className="size-4" />
              </Button>
            </FxTooltip>
          ))}
          <span aria-hidden="true" className="mx-0.5 h-5 w-px bg-(--fx-line)" />
          <FxTooltip label="Insert link">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className={TOOL_CLASS}
              aria-label="Insert link"
              disabled={disabled}
              onMouseDown={(e) => {
                e.preventDefault();
                applyLink();
              }}
              onClick={(e) => {
                if (e.detail === 0) applyLink();
              }}
            >
              <Link2 aria-hidden="true" className="size-4" />
            </Button>
          </FxTooltip>
        </div>

        <div
          ref={ref}
          role="textbox"
          aria-label={ariaLabel}
          aria-multiline="true"
          data-testid="rich-text-editable"
          contentEditable={!disabled}
          suppressContentEditableWarning
          className="max-h-[18rem] min-h-24 resize-y overflow-y-auto px-3 py-2 text-sm leading-relaxed text-(--fx-ink) outline-none [&_a]:text-(--fx-link) [&_a]:underline [&_ol]:list-decimal [&_ol]:ps-5 [&_ul]:list-disc [&_ul]:ps-5"
          onInput={commit}
          onBlur={() => {
            rememberSelection();
            commit();
          }}
          onKeyUp={rememberSelection}
          onMouseUp={rememberSelection}
        />
      </div>

      {fields.length > 0 && (
        <div className="flex flex-wrap items-center gap-1" aria-label="Merge fields">
          {fields.map((field) => (
            <button
              key={field.key}
              type="button"
              data-testid={`merge-chip-${field.key}`}
              disabled={disabled}
              className={cn(
                'inline-flex h-6 items-center rounded-(--fx-r-pill) bg-(--fx-chip) px-2.5 text-xs font-semibold text-(--fx-chip-ink) transition-colors duration-(--fx-t-hover) ease-(--fx-ease-out) hover:bg-(--fx-link-bg) hover:text-(--fx-link) disabled:opacity-50',
                PRESSED_CLASS,
              )}
              onMouseDown={(e) => {
                e.preventDefault();
                if (!disabled) insertToken(field.key);
              }}
              onClick={(e) => {
                if (e.detail === 0 && !disabled) insertToken(field.key);
              }}
            >
              {field.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
