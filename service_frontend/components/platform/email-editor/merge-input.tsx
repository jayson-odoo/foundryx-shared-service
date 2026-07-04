'use client';

import { useRef, useState, type RefObject } from 'react';
import { Braces } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { TemplateContextFact } from '@/types/templates';
import { MergeFieldBuilder } from './merge-field-builder';

/**
 * Single-field merge-token input — text field + a `{ }` insert BUILDER (same
 * shell idiom as the form engine's FormulaBuilder). The field vocabulary lives
 * in a searchable builder dialog with a live preview, NOT a flat always-on chip
 * wall (which grew unbounded as a context's fact set grew — user feedback).
 */

export interface MergeInputProps {
  value: string;
  onChange: (value: string) => void;
  fields: TemplateContextFact[];
  placeholder?: string;
  disabled?: boolean;
  multiline?: boolean;
  rows?: number;
  'aria-label'?: string;
}

export function MergeInput({
  value,
  onChange,
  fields,
  placeholder,
  disabled,
  multiline = false,
  rows = 4,
  'aria-label': ariaLabel,
}: MergeInputProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [builderOpen, setBuilderOpen] = useState(false);

  return (
    <div className="flex flex-col gap-1.5">
      {multiline ? (
        <Textarea
          ref={textareaRef as RefObject<HTMLTextAreaElement>}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={rows}
          disabled={disabled}
          aria-label={ariaLabel}
        />
      ) : (
        <Input
          ref={inputRef as RefObject<HTMLInputElement>}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          aria-label={ariaLabel}
        />
      )}
      {fields.length > 0 && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-label="Insert merge field"
          disabled={disabled}
          onClick={() => setBuilderOpen(true)}
          className="h-7 w-fit gap-1 px-2 text-xs font-normal text-muted-foreground"
        >
          <Braces className="size-3.5" />
          Insert field
        </Button>
      )}
      <MergeFieldBuilder
        open={builderOpen}
        onOpenChange={setBuilderOpen}
        value={value}
        onChange={onChange}
        fields={fields}
        multiline={multiline}
        title={ariaLabel ? `Insert field — ${ariaLabel}` : 'Insert field'}
      />
    </div>
  );
}
