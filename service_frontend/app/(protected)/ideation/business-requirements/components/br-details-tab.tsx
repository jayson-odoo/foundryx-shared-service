'use client';

import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { FormRow } from '@/components/platform/resource-form';
import { FormRenderer } from '@/components/platform/form-renderer';
import type { FormAnswers, FormDocument, FormFieldErrors } from '@/types/forms';

export interface BrDetailsTabProps {
  editing: boolean;
  title: string;
  onTitleChange: (title: string) => void;
  /** The BR's STAMPED template block document (never the active version). */
  doc: FormDocument;
  answers: FormAnswers;
  onAnswersChange: (answers: FormAnswers) => void;
  /** Server 422 per-field map from a failed save / promote (AC-BI-34b) — merged
   * into the renderer's inline field errors. */
  serverErrors?: FormFieldErrors;
}

/**
 * Details tab — renders ``answers`` through the form-engine renderer against the
 * BR's STAMPED template doc (AC-BI-16). Read mode when not editing; fill mode
 * (no submit button — the shell's global Save persists) when editing.
 */
export function BrDetailsTab({
  editing,
  title,
  onTitleChange,
  doc,
  answers,
  onAnswersChange,
  serverErrors,
}: BrDetailsTabProps) {
  const hasDoc = Boolean(doc?.pages?.length);
  return (
    <Card>
      <CardContent className="py-4 space-y-6">
        <FormRow label="Title" required={editing}>
          {editing ? (
            <Input
              value={title}
              onChange={(e) => onTitleChange(e.target.value)}
              className="max-w-md"
            />
          ) : (
            title || '—'
          )}
        </FormRow>

        {hasDoc ? (
          <FormRenderer
            definition={doc}
            mode={editing ? 'fill' : 'read'}
            answers={answers}
            onChange={onAnswersChange}
            errors={serverErrors}
          />
        ) : (
          <p className="text-sm text-muted-foreground">
            No template is configured for this requirement.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
