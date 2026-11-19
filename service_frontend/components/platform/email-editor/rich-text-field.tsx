'use client';

import { Bold, Italic, Link2, List, ListOrdered, Underline } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { TemplateContextFact } from '@/types/templates';
import { useFx } from '@/hooks/use-fx';
import { exec, useRichTextField } from './use-rich-text-field';
import { FxRichTextField } from './fx-rich-text-field';

/**
 * WYSIWYG rich-text field for Text blocks (plan sprint-2/07). A toolbar drives
 * formatting via execCommand so the user NEVER types raw tags - that produced
 * literal, escaped `&lt;i&gt;` in the output. The command set is deliberately
 * limited to the email-safe vocabulary nh3 keeps server-side (b/i/u/a/ul/ol).
 *
 * Single writer: React never re-applies innerHTML while focused (the
 * contentEditable race we already fixed once) - the sync effect seeds it, the
 * user owns it after, commit fires on blur + after each command.
 */

export interface RichTextFieldProps {
  value: string;
  onChange: (html: string) => void;
  fields: TemplateContextFact[];
  disabled?: boolean;
  'aria-label'?: string;
}

export function RichTextField(props: RichTextFieldProps) {
  // Foundryx UIUX switch: the playbook's slim toolbar along the field's top
  // edge while on; today's field while off. Both run the same commands
  // through `useRichTextField`, so the saved HTML is the same.
  return useFx() ? <FxRichTextField {...props} /> : <RichTextFieldLegacy {...props} />;
}

function RichTextFieldLegacy({
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
