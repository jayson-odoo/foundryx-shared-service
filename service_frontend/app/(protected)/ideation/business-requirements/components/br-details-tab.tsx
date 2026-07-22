'use client';

import { Card, CardContent } from '@/components/ui/card';
import { FormRenderer } from '@/components/platform/form-renderer';
import type { FormAnswers, FormDocument, FormFieldErrors } from '@/types/forms';

export interface BrDetailsTabProps {
  editing: boolean;
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
 *
 * Rendered FLAT (AC-BI-29c): the renderer's `flat` mode omits the template's
 * page/section titles ("Business Requirement" / "Requirement") so the fields
 * start straight at Problem statement. The BR title shows in the page header, so
 * no separate Title row is rendered here.
 */
export function BrDetailsTab({
  editing,
  doc,
  answers,
  onAnswersChange,
  serverErrors,
}: BrDetailsTabProps) {
  const hasDoc = Boolean(doc?.pages?.length);
  return (
    <Card>
      <CardContent className="py-4">
        {hasDoc ? (
          <FormRenderer
            definition={doc}
            mode={editing ? 'fill' : 'read'}
            answers={answers}
            onChange={onAnswersChange}
            errors={serverErrors}
            flat
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
