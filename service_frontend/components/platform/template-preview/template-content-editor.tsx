'use client';

/**
 * Per-use template content editor - a COPY of a template's block document that
 * the operator edits IN PLACE (wording only; structure is locked - rearranging
 * blocks belongs in the Templates engine). Reuses the full `EmailEditor` (brand
 * header/footer/blocks render exactly like the email) in `structureLocked`
 * mode, in a roomy dialog. Used by status notifications + workflow email
 * actions that store their own edited doc.
 */
import { useEffect, useState } from 'react';
import { EmailEditor } from '@/components/platform/email-editor';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { templateEngineService } from '@/services/template-service';
import type { TemplateContextFact, TemplateDocument } from '@/types/templates';

export interface TemplateContentEditorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  doc: TemplateDocument;
  subject: string;
  /** Template context key - its facts back the merge chips + preview render. */
  contextKey: string;
  onDocChange: (doc: TemplateDocument) => void;
  onSubjectChange: (subject: string) => void;
  title?: string;
  /** Read-only (form not in edit mode). */
  disabled?: boolean;
}

export function TemplateContentEditor({
  open,
  onOpenChange,
  doc,
  subject,
  contextKey,
  onDocChange,
  onSubjectChange,
  title = 'Edit email content',
  disabled = false,
}: TemplateContentEditorProps) {
  const [mergeFields, setMergeFields] = useState<TemplateContextFact[]>([]);

  useEffect(() => {
    if (!open) return;
    templateEngineService
      .listContexts()
      .then((contexts) => setMergeFields(contexts.find((c) => c.key === contextKey)?.facts ?? []))
      .catch(() => undefined);
  }, [open, contextKey]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          <div className="flex max-w-xl flex-col gap-1.5">
            <Label className="text-xs font-medium text-muted-foreground">Subject</Label>
            <Input
              value={subject}
              onChange={(e) => onSubjectChange(e.target.value)}
              placeholder="Subject - e.g. {{recordLabel}} moved to {{toStatus}}"
              disabled={disabled}
            />
          </div>
          <EmailEditor
            doc={doc}
            onChange={onDocChange}
            editing={!disabled}
            structureLocked
            mergeFields={mergeFields}
            visibilityFacts={[]}
            renderPreview={(d) => templateEngineService.preview(d, contextKey, subject)}
          />
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
