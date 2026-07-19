'use client';

import { useEffect } from 'react';
import { Upload, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  useFileUpload,
  formatBytes,
  type FileWithPreview,
} from '@/hooks/use-file-upload';
import type { IdeaAttachmentKind } from '@/types/ideation';

export interface DroppedAttachment {
  kind: IdeaAttachmentKind;
  name: string;
  sizeBytes?: number;
}

function kindOf(mime: string): IdeaAttachmentKind {
  if (mime.startsWith('image/')) return 'image';
  if (mime.startsWith('video/')) return 'video';
  if (mime.startsWith('audio/')) return 'audio';
  return 'file';
}

/**
 * Multi-file attachment drop area (voice note / image / video / file). Reuses
 * the system `useFileUpload` hook + the repo's canonical drop-area markup
 * (files-upload.tsx). Lifts a normalized attachment list to the parent form.
 */
export function AttachmentDrop({
  onChange,
}: {
  onChange: (attachments: DroppedAttachment[]) => void;
}) {
  const [
    { files, isDragging, errors },
    {
      removeFile,
      handleDragEnter,
      handleDragLeave,
      handleDragOver,
      handleDrop,
      openFileDialog,
      getInputProps,
    },
  ] = useFileUpload({
    multiple: true,
    maxFiles: 10,
    maxSize: 25 * 1024 * 1024,
    accept: 'image/*,video/*,audio/*,application/pdf,*',
  });

  useEffect(() => {
    onChange(
      files.map((f: FileWithPreview) => ({
        kind: kindOf(f.file.type ?? ''),
        name: f.file.name,
        sizeBytes: f.file.size,
      })),
    );
  }, [files, onChange]);

  return (
    <div className="space-y-2">
      <div
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        onClick={openFileDialog}
        className={cn(
          'relative flex cursor-pointer flex-col items-center gap-1.5 rounded-lg border border-dashed p-5 text-center transition-colors',
          isDragging
            ? 'border-primary bg-primary/5'
            : 'border-muted-foreground/25 hover:border-muted-foreground/50',
        )}
      >
        <input {...getInputProps()} className="sr-only" />
        <Upload className="size-5 text-muted-foreground" />
        <p className="text-sm font-medium">Drop voice notes, images, videos or files</p>
        <p className="text-xs text-muted-foreground">or click to browse · up to 25MB each</p>
      </div>

      {files.map((f) => (
        <div
          key={f.id}
          className="flex items-center justify-between rounded-md border px-2.5 py-1.5 text-sm"
        >
          <span className="min-w-0 truncate">
            {f.file.name}
            <span className="ms-1 text-muted-foreground">({formatBytes(f.file.size)})</span>
          </span>
          <button
            type="button"
            aria-label={`Remove ${f.file.name}`}
            onClick={(e) => {
              e.stopPropagation();
              removeFile(f.id);
            }}
            className="ms-2 rounded p-1 text-muted-foreground hover:bg-muted"
          >
            <X className="size-4" />
          </button>
        </div>
      ))}

      {errors.map((e, i) => (
        <p key={i} className="text-xs text-destructive">
          {e}
        </p>
      ))}
    </div>
  );
}
