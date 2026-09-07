'use client';

/**
 * One CSV upload field (S6, AC-MIG-46/47) - the repo's upload primitive
 * (`import-modal.tsx`'s dropzone-plus-hidden-input convention: drag/drop or
 * click, then a real multipart POST) reused for the migration setup form's
 * two upload slots: the CSV-mode contacts file (required when `source ===
 * 'csv'`) and the optional quick-replies snippets file (either mode, D-A6-19
 * - respond.io has no snippets endpoint).
 */
import { useRef, useState } from 'react';
import { LoaderCircle, UploadCloud, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { toast } from '@/lib/toast';
import { respondioMigrationService } from '@/services/respondio-migration-service';
import type { MigrationUploadResult } from '@/types/respondio-migration';

export interface CsvUploadFieldProps {
  kind: 'contacts' | 'snippets';
  label: string;
  editing: boolean;
  fileName: string | null;
  rowCount: number | null;
  onUploaded: (result: MigrationUploadResult, fileName: string) => void;
  onClear: () => void;
  error?: string;
}

export function CsvUploadField({
  kind,
  label,
  editing,
  fileName,
  rowCount,
  onUploaded,
  onClear,
  error,
}: CsvUploadFieldProps) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  const pick = async (file: File) => {
    setUploading(true);
    try {
      const result = await respondioMigrationService.uploadCsv(kind, file);
      onUploaded(result, file.name);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Upload failed.');
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  return (
    <div className="space-y-1.5">
      <label className="text-sm text-muted-foreground">{label}</label>
      {fileName ? (
        <div className="border-input flex items-center justify-between gap-3 rounded-lg border p-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{fileName}</p>
            {rowCount !== null && <p className="text-muted-foreground text-xs">{rowCount} rows</p>}
          </div>
          {editing && (
            <button
              type="button"
              aria-label={`Remove ${label}`}
              className={cn(PRESSED_CLASS, 'text-muted-foreground hover:text-foreground shrink-0')}
              onClick={onClear}
            >
              <X className="size-4" />
            </button>
          )}
        </div>
      ) : (
        <div
          className={cn(
            'border-input flex cursor-pointer flex-col items-center gap-2 rounded-lg border border-dashed p-5 text-center',
            !editing && 'pointer-events-none opacity-60',
          )}
          onClick={() => fileInput.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            if (editing && e.dataTransfer.files[0]) void pick(e.dataTransfer.files[0]);
          }}
        >
          {uploading ? (
            <LoaderCircle className="text-muted-foreground size-5 animate-spin" />
          ) : (
            <UploadCloud className="text-muted-foreground size-5" />
          )}
          <span className="text-sm">Drop a file or click to choose (csv, xlsx, xls)</span>
          <input
            ref={fileInput}
            type="file"
            accept=".csv,.xlsx,.xls"
            className="hidden"
            disabled={!editing}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void pick(f);
            }}
          />
        </div>
      )}
      {error && <p className="text-destructive text-xs">{error}</p>}
    </div>
  );
}
