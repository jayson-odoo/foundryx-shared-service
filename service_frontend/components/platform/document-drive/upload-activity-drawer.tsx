'use client';

import { AlertTriangle, CheckCircle2, RotateCw, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { cn } from '@/lib/utils';
import type { UploadFileItem } from '@/types/documents';
import { formatBytes } from './lib';
import { useUploadManager } from './upload-manager';

/** Global right-side drawer surfacing upload progress, decoupled from the page. */
export function UploadActivityDrawer() {
  const { items, open, setOpen, resolveConflict, retry, remove, clearFinished } =
    useUploadManager();

  const finished = items.filter((it) => it.status === 'done' || it.status === 'failed').length;

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-md">
        <SheetHeader className="flex-row items-center justify-between border-b px-4 py-3">
          <SheetTitle>Uploads</SheetTitle>
          {finished > 0 && (
            <Button variant="ghost" size="sm" onClick={clearFinished}>
              Clear finished
            </Button>
          )}
        </SheetHeader>

        <div className="flex-1 overflow-y-auto">
          {items.length === 0 ? (
            <p className="p-6 text-center text-sm text-muted-foreground">No uploads yet.</p>
          ) : (
            <ul className="divide-y">
              {items.map((it) => (
                <UploadRow
                  key={it.id}
                  item={it}
                  onResolve={resolveConflict}
                  onRetry={retry}
                  onRemove={remove}
                />
              ))}
            </ul>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function UploadRow({
  item,
  onResolve,
  onRetry,
  onRemove,
}: {
  item: UploadFileItem;
  onResolve: (id: string, mode: 'replace' | 'keep_both') => void;
  onRetry: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  return (
    <li className="px-4 py-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium" title={item.name}>
            {item.name}
          </p>
          <p className="text-xs text-muted-foreground">{formatBytes(item.sizeBytes)}</p>
        </div>
        <StatusIcon status={item.status} />
      </div>

      {(item.status === 'uploading' || item.status === 'queued') && (
        <Progress value={item.progress} className="mt-2 h-1.5" />
      )}

      {item.status === 'failed' && (
        <div className="mt-2 flex items-center justify-between gap-2">
          <p className="text-xs text-destructive">{item.error}</p>
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" onClick={() => onRetry(item.id)}>
              <RotateCw className="size-3.5" /> Retry
            </Button>
            <Button variant="ghost" size="icon" className="size-7" onClick={() => onRemove(item.id)}>
              <X className="size-3.5" />
            </Button>
          </div>
        </div>
      )}

      {item.status === 'conflict' && (
        <div className="mt-2 rounded-md border border-amber-300 bg-amber-50 p-2 dark:border-amber-800 dark:bg-amber-950/40">
          <p className="text-xs text-amber-800 dark:text-amber-300">
            A file named “{item.conflict?.fileName}” already exists here.
          </p>
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="outline" onClick={() => onResolve(item.id, 'keep_both')}>
              Keep both
            </Button>
            <Button size="sm" onClick={() => onResolve(item.id, 'replace')}>
              Replace
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

function StatusIcon({ status }: { status: UploadFileItem['status'] }) {
  if (status === 'done') return <CheckCircle2 className="size-4 shrink-0 text-green-600" />;
  if (status === 'failed') return <AlertTriangle className="size-4 shrink-0 text-destructive" />;
  if (status === 'conflict')
    return <AlertTriangle className="size-4 shrink-0 text-amber-500" />;
  return (
    <span
      className={cn(
        'mt-1 size-2 shrink-0 rounded-full bg-primary',
        status === 'uploading' && 'animate-pulse',
      )}
    />
  );
}
