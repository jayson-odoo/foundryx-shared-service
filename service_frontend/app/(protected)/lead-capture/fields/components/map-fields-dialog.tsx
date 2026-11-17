'use client';

import { useEffect, useState } from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';
import { toast } from '@/lib/toast';
import { Alert, AlertIcon, AlertTitle, AlertToolbar } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ClampedText } from '@/components/platform/clamped-text';
import { SearchSelect } from '@/components/platform/search-select';
import { leadCaptureErrorMessage, useFormQuestions, useSaveFieldMap } from '@/hooks/use-lead-capture';
import { fieldMapPayload, initialTargets, targetOptions } from '@/lib/lead-field-map';
import type { LeadField, LeadSourceItem } from '@/types/lead-capture';

export interface MapTarget {
  sourceId: string;
  formId: string;
  formName: string;
}

export interface MapFieldsDialogProps {
  target: MapTarget | null;
  sources: LeadSourceItem[];
  fields: LeadField[];
  canManage: boolean;
  onClose: () => void;
  onSaved: () => void;
}

/** The popup is mounted per target so its questions load fresh each open. */
export function MapFieldsDialog(props: MapFieldsDialogProps) {
  const { target, onClose } = props;
  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        {target && <MapFieldsBody key={`${target.sourceId}:${target.formId}`} {...props} target={target} />}
      </DialogContent>
    </Dialog>
  );
}

function MapFieldsBody({
  target,
  sources,
  fields,
  canManage,
  onClose,
  onSaved,
}: MapFieldsDialogProps & { target: MapTarget }) {
  const questions = useFormQuestions(target.sourceId, target.formId);
  const { saving, save } = useSaveFieldMap();
  const [selection, setSelection] = useState<Record<string, string>>({});
  const source = sources.find((s) => s.id === target.sourceId);
  const title = questions.data?.formName || target.formName;

  useEffect(() => {
    if (questions.data) {
      setSelection(initialTargets(questions.data.data, source?.fieldMap ?? {}, target.formId, fields));
    }
  }, [questions.data, source, target.formId, fields]);

  const onSave = async () => {
    if (!questions.data) return;
    try {
      await save(target.sourceId, target.formId, fieldMapPayload(questions.data.data, selection));
      toast.success('Field map saved.');
      onSaved();
      onClose();
    } catch (err) {
      toast.error(leadCaptureErrorMessage(err, 'Could not save the field map. Please try again.'));
    }
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle>
          <ClampedText text={`Map fields: ${title}`} lines={1} />
        </DialogTitle>
      </DialogHeader>
      <DialogBody>
        {questions.loading && !questions.data && <Loader2 className="size-5 animate-spin text-muted-foreground" />}
        {questions.error && (
          <Alert variant="destructive">
            <AlertIcon>
              <AlertCircle />
            </AlertIcon>
            <AlertTitle>{questions.error}</AlertTitle>
            <AlertToolbar>
              <Button variant="outline" size="sm" onClick={questions.reload}>
                Try again
              </Button>
            </AlertToolbar>
          </Alert>
        )}
        {questions.data && questions.data.data.length === 0 && (
          <p className="text-sm text-muted-foreground">This form has no questions.</p>
        )}
        {questions.data && questions.data.data.length > 0 && (
          <div className="flex flex-col divide-y">
            <div className="grid grid-cols-1 gap-2 pb-2 text-xs font-medium text-muted-foreground sm:grid-cols-2">
              <span>Question</span>
              <span className="hidden sm:block">Lead field</span>
            </div>
            {questions.data.data.map((q) => (
              <div key={q.key} className="grid grid-cols-1 items-center gap-2 py-2 sm:grid-cols-2">
                <ClampedText text={q.label} lines={1} className="text-sm" />
                <SearchSelect
                  ariaLabel={q.label}
                  options={targetOptions(q, fields)}
                  value={selection[q.key] ?? ''}
                  disabled={!canManage}
                  onChange={(v) => setSelection((prev) => ({ ...prev, [q.key]: v }))}
                />
              </div>
            ))}
          </div>
        )}
      </DialogBody>
      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={saving}>
          {canManage ? 'Cancel' : 'Close'}
        </Button>
        {canManage && (
          <Button variant="primary" onClick={onSave} disabled={saving || !questions.data}>
            {saving && <Loader2 className="size-4 animate-spin" />}
            Save
          </Button>
        )}
      </DialogFooter>
    </>
  );
}
