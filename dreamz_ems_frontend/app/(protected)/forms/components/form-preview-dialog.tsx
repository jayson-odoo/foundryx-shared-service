'use client';

/** Author preview (plan sprint-3/01 D9) — renders the DRAFT through the one
 * runtime renderer in a roomy dialog. Interactive (conditions/computed run
 * live) but never submits; answers are throwaway. */
import { useEffect, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { FormRenderer } from '@/components/platform/form-renderer';
import type { FormAnswers, FormDocument } from '@/types/forms';

export interface FormPreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  name: string;
  definition: FormDocument | null;
  paged: boolean;
}

export function FormPreviewDialog({
  open,
  onOpenChange,
  name,
  definition,
  paged,
}: FormPreviewDialogProps) {
  const [answers, setAnswers] = useState<FormAnswers>({});

  // Fresh sheet per open — a preview session's answers are not state.
  useEffect(() => {
    if (open) setAnswers({});
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] w-[min(960px,95vw)] max-w-none flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle>{name} — preview</DialogTitle>
        </DialogHeader>
        <div className="grow overflow-y-auto pe-1" data-testid="form-preview">
          {definition && (
            <FormRenderer
              definition={definition}
              mode="fill"
              answers={answers}
              onChange={setAnswers}
              paged={paged}
              submitLabel="Submit (preview)"
              onSubmit={() => onOpenChange(false)}
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
