'use client';

/**
 * The import dialog under the Foundryx UIUX switch (slice W3-JOBS): step 1 of
 * the import wizard, the file. Same choices as today (mode, file, template)
 * and the same upload request; after it the import page carries on with
 * matching the columns, the check and the import, exactly as the switch-off
 * dialog hands over today.
 */
import { useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { SearchSelect } from '@/components/platform/search-select';
import { FxFileIcon } from '@/components/fx/icons';
import { useHideMainAction } from '@/components/fx/actions/page-actions-context';
import { cn } from '@/lib/utils';
import { importService } from '@/services/import-service';
import type { ImportConfig, ImportMode } from '@/types/import';
import { MODE_LABELS, TemplateDialog, type ImportModalProps } from './import-modal';
import { FxImportSteps } from './fx-import-steps';

export function FxImportModal({ entityType, context, onClose }: ImportModalProps) {
  const router = useRouter();
  const origin = usePathname(); // the list the import was launched from
  const [config, setConfig] = useState<ImportConfig | null>(null);
  const [mode, setMode] = useState<ImportMode>('create_only');
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  // The dialog's button is the one red action while it is open.
  useHideMainAction(true);

  useEffect(() => {
    let active = true;
    importService
      .getConfig(entityType)
      .then((c) => active && setConfig(c))
      .catch((e) => active && setError(e instanceof Error ? e.message : 'Failed to load.'));
    return () => {
      active = false;
    };
  }, [entityType]);

  // The same request the switch-off dialog sends.
  const start = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const { jobId } = await importService.create({
        entityType,
        mode,
        // Abort + Trigger-automations are chosen on the import page (at Import).
        abortOnInvalid: false,
        triggerAutomations: false,
        context,
        file,
      });
      onClose();
      router.push(`/imports/${jobId}?from=${encodeURIComponent(origin)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed.');
      setBusy(false);
    }
  };

  const noun = config?.label ?? entityType;
  const nextLabel = busy ? 'Uploading…' : 'Next';

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Import {noun}</DialogTitle>
          <DialogDescription className="sr-only">
            Import {noun} from a CSV or Excel file
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-5">
          <FxImportSteps current={0} />
          {!config ? (
            <Skeleton className="h-48 w-full" />
          ) : (
            <>
              <div className="flex flex-col gap-1.5">
                <Label>Mode</Label>
                <SearchSelect
                  ariaLabel="Mode"
                  value={mode}
                  onChange={(v) => setMode(v as ImportMode)}
                  options={config.modes.map((m) => ({ value: m, label: MODE_LABELS[m] }))}
                />
              </div>

              <button
                type="button"
                data-fx-pulse-target="import-file"
                className={cn(
                  PRESSED_CLASS,
                  'flex flex-col items-center gap-2 rounded-(--fx-r-l) border border-dashed px-6 py-8 text-center transition-colors duration-(--fx-t-hover) ease-(--fx-ease-out)',
                  dragging
                    ? 'border-(--fx-link) bg-(--fx-link-bg)'
                    : 'border-(--fx-line-2) bg-(--fx-surface-2) hover:border-(--fx-ink-3)',
                )}
                onClick={() => fileInput.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragging(false);
                  if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
                }}
              >
                <FxFileIcon type="CSV" arrow="up" size={24} className="text-(--fx-ink-3)" />
                {file ? (
                  <span className="text-sm font-semibold break-all text-(--fx-ink)">{file.name}</span>
                ) : (
                  <span className="text-sm text-(--fx-ink-2)">CSV or Excel (.csv, .xlsx, .xls)</span>
                )}
              </button>
              <input
                ref={fileInput}
                type="file"
                accept=".xlsx,.xls,.csv"
                aria-label="File to import"
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />

              <div>
                <Button
                  type="button"
                  variant="fx-text"
                  size="sm"
                  className="-ms-2"
                  onClick={() => setTemplateOpen(true)}
                >
                  <FxFileIcon type="CSV" arrow="down" size={16} /> Download a template
                </Button>
              </div>

              {error && (
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              )}
            </>
          )}
        </DialogBody>
        <DialogFooter className="flex-row items-start justify-between gap-2 sm:justify-between">
          <Button variant="fx-quiet" onClick={onClose} disabled={busy}>
            Close
          </Button>
          <div className="flex items-start gap-2">
            <Button variant="fx-quiet" disabled>
              Back
            </Button>
            <div className="flex flex-col items-end gap-1">
              <Button
                variant="fx-main"
                onClick={() => void start()}
                disabled={!file || busy}
                aria-describedby={!file ? 'fx-import-next-why' : undefined}
              >
                {nextLabel}
              </Button>
              {!file && config && (
                <span id="fx-import-next-why" className="text-xs text-(--fx-ink-3)">
                  Choose a file.
                </span>
              )}
            </div>
          </div>
        </DialogFooter>
      </DialogContent>

      {config && templateOpen && (
        <TemplateDialog
          entityType={entityType}
          columns={config.columns}
          onClose={() => setTemplateOpen(false)}
        />
      )}
    </Dialog>
  );
}
