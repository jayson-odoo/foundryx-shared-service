'use client';

/**
 * Merge-field template editor (sprint-2/01 review mandate) — subject + body
 * with CLICK-TO-INSERT variable chips (no typing {{tokens}} by hand) and a
 * live PREVIEW rendered with the provided context. Generic on purpose: the
 * notification sub-form uses it today; the Template engine (BL-024) adopts
 * it as the standard template-builder input.
 *
 * The narrow side panel is cramped for a multi-line email, so an EXPAND button
 * opens a roomy dialog with the editor on the left and a live rendered preview
 * on the right (verify the merged result before saving).
 */
import { useRef, useState } from 'react';
import { Eye, EyeOff, Maximize2, Plus } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

export interface MergeField {
  /** Token key — inserted as {{key}}. */
  key: string;
  /** Chip label shown to the user. */
  label: string;
}

const TOKEN_RE = /\{\{\s*(\w+)\s*\}\}/g;

/** Same semantics as the backend's render_inline — unknown fields go empty. */
export function renderTemplate(template: string, context: Record<string, string>): string {
  return (template ?? '').replace(TOKEN_RE, (_, key: string) => context[key] ?? '');
}

export interface MergeFieldEditorProps {
  subject: string;
  body: string;
  onSubjectChange: (value: string) => void;
  onBodyChange: (value: string) => void;
  fields: MergeField[];
  /** Values the preview renders with (real edge/entity/actor + sample record). */
  previewContext: Record<string, string>;
  subjectPlaceholder?: string;
  bodyPlaceholder?: string;
  disabled?: boolean;
  /** Title shown on the expanded dialog. */
  dialogTitle?: string;
}

export function MergeFieldEditor({
  subject,
  body,
  onSubjectChange,
  onBodyChange,
  fields,
  previewContext,
  subjectPlaceholder = 'Subject…',
  bodyPlaceholder = 'Body…',
  disabled = false,
  dialogTitle = 'Edit email',
}: MergeFieldEditorProps) {
  const subjectRef = useRef<HTMLInputElement>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const [lastFocused, setLastFocused] = useState<'subject' | 'body'>('body');
  const [showPreview, setShowPreview] = useState(false);
  const [expanded, setExpanded] = useState(false);

  /** Insert {{key}} at the caret of the last-focused field (body default). */
  const insert = (key: string) => {
    const token = `{{${key}}}`;
    const intoSubject = lastFocused === 'subject';
    const element = intoSubject ? subjectRef.current : bodyRef.current;
    const value = intoSubject ? subject : body;
    // Caret position only means something while the field is focused —
    // otherwise append at the end (clicking a chip cold shouldn't prepend).
    const hasCaret = element != null && document.activeElement === element;
    const start = hasCaret ? (element.selectionStart ?? value.length) : value.length;
    const end = hasCaret ? (element.selectionEnd ?? value.length) : value.length;
    const next = value.slice(0, start) + token + value.slice(end);
    (intoSubject ? onSubjectChange : onBodyChange)(next);
    // Restore focus + caret after the controlled re-render.
    requestAnimationFrame(() => {
      element?.focus();
      const caret = start + token.length;
      element?.setSelectionRange(caret, caret);
    });
  };

  const chips = (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-2xs text-muted-foreground">Insert:</span>
      {fields.map((field) => (
        <button
          key={field.key}
          type="button"
          disabled={disabled}
          onClick={() => insert(field.key)}
          aria-label={`Insert ${field.label}`}
          className="disabled:opacity-50"
        >
          <Badge variant="secondary" appearance="light" size="sm" className="cursor-pointer">
            <Plus className="size-2.5" />
            {field.label}
          </Badge>
        </button>
      ))}
    </div>
  );

  const editor = (bodyRows: number) => (
    <>
      <Input
        ref={subjectRef}
        value={subject}
        onChange={(e) => onSubjectChange(e.target.value)}
        onFocus={() => setLastFocused('subject')}
        placeholder={subjectPlaceholder}
        disabled={disabled}
      />
      <Textarea
        ref={bodyRef}
        value={body}
        onChange={(e) => onBodyChange(e.target.value)}
        onFocus={() => setLastFocused('body')}
        placeholder={bodyPlaceholder}
        rows={bodyRows}
        disabled={disabled}
      />
    </>
  );

  const previewPane = (
    <div data-testid="template-preview" className="flex flex-col gap-2">
      <div className="flex min-h-8.5 items-center rounded-md border border-dashed border-input bg-muted/40 px-3 py-1.5 text-sm font-medium text-foreground">
        {renderTemplate(subject, previewContext) || (
          <span className="font-normal text-muted-foreground">(empty subject)</span>
        )}
      </div>
      <div className="min-h-19 flex-1 whitespace-pre-wrap rounded-md border border-dashed border-input bg-muted/40 px-3 py-2 text-sm text-foreground">
        {renderTemplate(body, previewContext) || (
          <span className="text-muted-foreground">(empty body)</span>
        )}
      </div>
    </div>
  );

  return (
    <div className="flex flex-col gap-2">
      {showPreview ? previewPane : editor(3)}

      <div className="flex flex-wrap items-center gap-1.5">
        {showPreview ? (
          <span className="text-2xs text-muted-foreground">Previewing with sample values</span>
        ) : (
          chips
        )}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="ms-auto"
          onClick={() => setShowPreview((v) => !v)}
        >
          {showPreview ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
          {showPreview ? 'Edit' : 'Preview'}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={() => setExpanded(true)}>
          <Maximize2 className="size-3.5" /> Expand
        </Button>
      </div>

      <Dialog open={expanded} onOpenChange={setExpanded}>
        <DialogContent className="max-w-4xl">
          <DialogHeader>
            <DialogTitle>{dialogTitle}</DialogTitle>
          </DialogHeader>
          <DialogBody className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <div className="flex flex-col gap-2">
              <Label className="text-xs font-medium text-muted-foreground">Edit</Label>
              {editor(16)}
              {!disabled && chips}
            </div>
            <div className="flex flex-col gap-2">
              <Label className="text-xs font-medium text-muted-foreground">
                Preview · sample values
              </Label>
              {previewPane}
            </div>
          </DialogBody>
        </DialogContent>
      </Dialog>
    </div>
  );
}
