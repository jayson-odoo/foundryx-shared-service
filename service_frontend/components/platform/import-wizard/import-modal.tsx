'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
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
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { cn } from '@/lib/utils';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { SearchSelect } from '@/components/platform/search-select';
import { Skeleton } from '@/components/ui/skeleton';
import { importService } from '@/services/import-service';
import type { ImportColumnDef, ImportConfig, ImportMode } from '@/types/import';
import { Download, UploadCloud } from 'lucide-react';

const MODE_LABELS: Record<ImportMode, string> = {
  create_only: 'Create new records only',
  update_only: 'Update existing records only',
  upsert: 'Create or update',
};

/**
 * Import wizard step 1 (sprint-3/09 D3/D4) - pick a mode + options, drop the
 * filled file → routes to the mapping page. Template options (format + which
 * columns) live in a SEPARATE dialog opened from "Download template" - the main
 * modal stays focused on the import itself.
 */
export function ImportModal({
  entityType,
  context,
  onClose,
}: {
  entityType: string;
  context?: Record<string, unknown>;
  onClose: () => void;
}) {
  const router = useRouter();
  const origin = usePathname(); // the list the import was launched from
  const [config, setConfig] = useState<ImportConfig | null>(null);
  const [mode, setMode] = useState<ImportMode>('create_only');
  const [file, setFile] = useState<File | null>(null);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

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

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Import {config?.label ?? entityType}</DialogTitle>
          <DialogDescription>
            Upload a filled file to validate, then map its columns.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-5">
          {!config ? (
            <Skeleton className="h-48 w-full" />
          ) : (
            <>
              <div className="space-y-1.5">
                <Label>Mode</Label>
                <SearchSelect
                  value={mode}
                  onChange={(v) => setMode(v as ImportMode)}
                  options={config.modes.map((m) => ({ value: m, label: MODE_LABELS[m] }))}
                />
              </div>

              <div
                className="border-input flex cursor-pointer flex-col items-center gap-2 rounded-lg border border-dashed p-6 text-center"
                onClick={() => fileInput.current?.click()}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
                }}
              >
                <UploadCloud className="text-muted-foreground size-6" />
                <span className="text-sm">
                  {file ? file.name : 'Drop a file or click to choose (xlsx, xls, csv)'}
                </span>
                <input
                  ref={fileInput}
                  type="file"
                  accept=".xlsx,.xls,.csv"
                  className="hidden"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
              </div>

              <button
                type="button"
                className={cn(PRESSED_CLASS, 'text-primary inline-flex items-center gap-1.5 text-sm font-medium hover:underline')}
                onClick={() => setTemplateOpen(true)}
              >
                <Download className="size-3.5" /> Download template
              </button>

              {error && <p className="text-destructive text-sm">{error}</p>}
            </>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void start()} disabled={!file || busy}>
            {busy ? 'Uploading…' : 'Upload & map'}
          </Button>
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

/**
 * Template options (plan sprint-3/09 D3) - shown ONLY when downloading a
 * template: choose the format + which columns to include. Required columns are
 * always in (checked + locked). Searchable, scrollable list - scales to many
 * columns (no pills).
 */
function TemplateDialog({
  entityType,
  columns,
  onClose,
}: {
  entityType: string;
  columns: ImportColumnDef[];
  onClose: () => void;
}) {
  const [format, setFormat] = useState<'xlsx' | 'csv'>('xlsx');
  const [search, setSearch] = useState('');
  // Optional columns selected for inclusion (required are always included).
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(columns.filter((c) => !c.required && c.key !== 'id').map((c) => c.key)),
  );
  const [busy, setBusy] = useState(false);

  const optional = useMemo(() => columns.filter((c) => !c.required), [columns]);
  const required = useMemo(() => columns.filter((c) => c.required), [columns]);
  const visibleOptional = useMemo(() => {
    const s = search.trim().toLowerCase();
    return s ? optional.filter((c) => c.label.toLowerCase().includes(s) || c.key.toLowerCase().includes(s)) : optional;
  }, [optional, search]);

  const toggle = (key: string) =>
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const allVisibleOn = visibleOptional.every((c) => selected.has(c.key));
  const toggleAllVisible = () =>
    setSelected((cur) => {
      const next = new Set(cur);
      if (allVisibleOn) visibleOptional.forEach((c) => next.delete(c.key));
      else visibleOptional.forEach((c) => next.add(c.key));
      return next;
    });

  const download = async () => {
    setBusy(true);
    try {
      const cols = [...required.map((c) => c.key), ...Array.from(selected)];
      const blob = await importService.downloadTemplate(entityType, cols, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${entityType}-import-template.${format}`;
      a.click();
      URL.revokeObjectURL(url);
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Download template</DialogTitle>
          <DialogDescription>Choose the format and which columns to include.</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label>Format</Label>
            <SearchSelect
              value={format}
              onChange={(v) => setFormat(v as 'xlsx' | 'csv')}
              options={[
                { value: 'xlsx', label: 'Excel (.xlsx)' },
                { value: 'csv', label: 'CSV (.csv)' },
              ]}
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Include columns</Label>
              {visibleOptional.length > 0 && (
                <button
                  type="button"
                  className={cn(PRESSED_CLASS, 'text-primary text-xs font-medium hover:underline')}
                  onClick={toggleAllVisible}
                >
                  {allVisibleOn ? 'Clear' : 'Select all'}
                </button>
              )}
            </div>
            <Input
              placeholder="Search columns…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <div className="max-h-60 space-y-0.5 overflow-y-auto rounded-md border p-1">
              {/* Required - always included, locked. */}
              {required.map((c) => (
                <label
                  key={c.key}
                  className="flex items-center gap-2 rounded px-2 py-1.5 text-sm opacity-70"
                >
                  <Checkbox checked disabled />
                  <span>{c.label}</span>
                  <span className="text-muted-foreground ms-auto text-xs">Required</span>
                </label>
              ))}
              {visibleOptional.map((c) => (
                <label
                  key={c.key}
                  className="hover:bg-accent flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm"
                >
                  <Checkbox checked={selected.has(c.key)} onCheckedChange={() => toggle(c.key)} />
                  <span>{c.label}</span>
                  {c.key === 'id' && (
                    <span className="text-muted-foreground ms-auto text-xs">to update existing</span>
                  )}
                </label>
              ))}
              {visibleOptional.length === 0 && required.length === 0 && (
                <p className="text-muted-foreground p-3 text-center text-xs">No columns match.</p>
              )}
            </div>
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void download()} disabled={busy}>
            {busy ? 'Preparing…' : `Download .${format}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
