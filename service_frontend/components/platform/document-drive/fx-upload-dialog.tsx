'use client';

/**
 * The upload dialog under the Foundryx UIUX switch (slice W3-DOCS): the same
 * two steps (an optional document type, then drop or choose files) and the
 * same hand-off to the upload queue, whose progress shows in the Jobs sheet.
 * The dialog names the folder the files go to; the words that told people
 * how to use it are gone (no instructional copy).
 */
import { useEffect, useRef, useState } from 'react';
import { UploadCloud } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { SearchSelect } from '@/components/platform/search-select';
import { FX_FIELD_LABEL } from '@/components/fx/fields';
import { documentService } from '@/services/document-service';
import { cn } from '@/lib/utils';
import type { AttachmentTypeRow } from '@/types/documents';
import type { UploadDialogProps } from './upload-dialog';
import { useUploadManager } from './upload-manager';

export function FxUploadDialog({
  open,
  folderId,
  folderName,
  onClose,
}: UploadDialogProps & { folderName: string }) {
  const uploads = useUploadManager();
  const [types, setTypes] = useState<AttachmentTypeRow[]>([]);
  const [typeId, setTypeId] = useState<string>('');
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setTypeId('');
    documentService
      .listTypes({ page: 0, pageSize: 200 })
      .then((res) => setTypes(res.data))
      .catch(() => setTypes([]));
  }, [open]);

  const send = (files: File[]) => {
    if (!files.length) return;
    uploads.enqueue(files, { folderId, attachmentTypeId: typeId || null });
    onClose();
  };

  const options = [
    { value: '', label: 'No type (uncategorized)' },
    ...types.map((t) => ({ value: t.id, label: t.name })),
  ];

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Upload files to {folderName}</DialogTitle>
          <DialogDescription className="sr-only">Upload files to {folderName}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label className={FX_FIELD_LABEL}>Document type</Label>
            <SearchSelect
              options={options}
              value={typeId}
              onChange={setTypeId}
              placeholder="No type (uncategorized)"
              ariaLabel="Document type"
            />
          </div>

          <div
            role="group"
            aria-label="Drop files"
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              send(Array.from(e.dataTransfer.files));
            }}
            className={cn(
              'flex flex-col items-center justify-center gap-3 rounded-(--fx-r-l) border-2 border-dashed px-6 py-8 text-center transition-colors duration-(--fx-t-hover) ease-(--fx-ease-out)',
              dragOver ? 'border-(--fx-link) bg-(--fx-link-bg)' : 'border-(--fx-line-2)',
            )}
          >
            <UploadCloud className="size-8 text-(--fx-ink-3)" aria-hidden="true" />
            <Button
              type="button"
              variant="fx-main"
              className={cn(PRESSED_CLASS, 'h-auto min-h-11 rounded-(--fx-r-pill) px-5')}
              onClick={() => inputRef.current?.click()}
            >
              Choose files
            </Button>
          </div>

          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            aria-label="Choose files"
            data-testid="fx-upload-input"
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = '';
              send(files);
            }}
          />
        </div>

        <DialogFooter>
          <Button variant="fx-quiet" onClick={onClose}>
            Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
