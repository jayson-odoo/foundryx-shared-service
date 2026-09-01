'use client';

import { useEffect, useRef, useState } from 'react';
import { UploadCloud } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import { documentService } from '@/services/document-service';
import { cn } from '@/lib/utils';
import type { AttachmentTypeRow } from '@/types/documents';
import { useUploadManager } from './upload-manager';

export interface UploadDialogProps {
  open: boolean;
  folderId: string | null;
  onClose: () => void;
}

/**
 * Upload entry point (sprint-3/04b): pick an optional document type, then drop
 * files OR browse - instead of jumping straight to the OS picker (which gave no
 * chance to set the type). Files enqueue to the global Uploads drawer with the
 * chosen type; progress is tracked there.
 */
export function UploadDialog({ open, folderId, onClose }: UploadDialogProps) {
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
          <DialogTitle>Upload files</DialogTitle>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label>Document type</Label>
            <SearchSelect
              options={options}
              value={typeId}
              onChange={setTypeId}
              placeholder="No type (uncategorized)"
            />
          </div>

          <button
            type="button"
            onClick={() => inputRef.current?.click()}
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
              'flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition',
              dragOver ? 'border-primary bg-primary/5' : 'border-input hover:border-primary/50',
            )}
          >
            <UploadCloud className="size-8 text-muted-foreground" />
            <p className="text-sm font-medium">Drop files here, or click to browse</p>
            <p className="text-xs text-muted-foreground">
              Uploads to the current folder; progress shows in the Uploads panel.
            </p>
          </button>

          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = '';
              send(files);
            }}
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
