'use client';

import { useEffect, useState } from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';
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
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import { useSourceForms } from '@/hooks/use-lead-capture';
import type { LeadSourceItem } from '@/types/lead-capture';
import type { MapTarget } from './map-fields-dialog';

export interface AddFormDialogProps {
  open: boolean;
  sources: LeadSourceItem[];
  onOpenChange: (open: boolean) => void;
  /** Hands the chosen Page + form to the Map fields popup. */
  onPick: (target: MapTarget) => void;
}

/** Pick the Page, then one of its Instant Forms (read from Meta); the map popup opens for it. */
export function AddFormDialog({ open, sources, onOpenChange, onPick }: AddFormDialogProps) {
  const [sourceId, setSourceId] = useState('');
  const [formId, setFormId] = useState('');
  const forms = useSourceForms(open ? sourceId : '');

  useEffect(() => {
    if (open) {
      setSourceId(sources.length === 1 ? sources[0].id : '');
      setFormId('');
    }
  }, [open, sources]);

  const formOptions = (forms.data?.data ?? []).map((f) => ({
    value: f.id,
    label: f.name?.trim() || `Instant Form ${f.id}`,
  }));
  const chosen = formOptions.find((o) => o.value === formId);

  const submit = () => {
    if (!sourceId || !chosen) return;
    onOpenChange(false);
    onPick({ sourceId, formId: chosen.value, formName: chosen.label });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Add form</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          {sources.length === 0 && (
            <p className="text-sm text-destructive">No Facebook Page is connected yet.</p>
          )}
          <div className="flex flex-col gap-2">
            <Label>Page *</Label>
            <SearchSelect
              ariaLabel="Page"
              options={sources.map((s) => ({ value: s.id, label: s.pageName || s.name }))}
              value={sourceId}
              onChange={(v) => {
                setSourceId(v);
                setFormId('');
              }}
            />
          </div>
          {sourceId && (
            <div className="flex flex-col gap-2">
              <Label>Form *</Label>
              {forms.loading && !forms.data && <Loader2 className="size-5 animate-spin text-muted-foreground" />}
              {forms.error && (
                <Alert variant="destructive">
                  <AlertIcon>
                    <AlertCircle />
                  </AlertIcon>
                  <AlertTitle>{forms.error}</AlertTitle>
                  <AlertToolbar>
                    <Button variant="outline" size="sm" onClick={forms.reload}>
                      Try again
                    </Button>
                  </AlertToolbar>
                </Alert>
              )}
              {forms.data && formOptions.length === 0 && (
                <p className="text-sm text-destructive">This Page has no Instant Forms.</p>
              )}
              {forms.data && formOptions.length > 0 && (
                <SearchSelect ariaLabel="Form" options={formOptions} value={formId} onChange={setFormId} />
              )}
            </div>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} disabled={!sourceId || !chosen}>
            Next
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
