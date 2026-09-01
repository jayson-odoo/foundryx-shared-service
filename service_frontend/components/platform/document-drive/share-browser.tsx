'use client';

/**
 * Read-only "mini Drive" for a share (plan sprint-3/05). The SAME component
 * serves the anonymous public page AND the in-app scoped view - same look as the
 * internal Documents Drive (card/list toggle, folder navigation, click-to-preview
 * for images/PDF, download), but limited to the shared subtree and nothing else.
 * An `edit` folder share also gets an Upload affordance. Driven by the
 * `usePublicShare` hook (mode-aware data source).
 */
import { useEffect, useRef, useState } from 'react';
import {
  ChevronRight,
  Download,
  File as FileIcon,
  FileText,
  Folder,
  Image as ImageIcon,
  LayoutGrid,
  List,
  Loader2,
  Upload,
} from 'lucide-react';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import { formatBytes } from './lib';
import type { UsePublicShare } from '@/hooks/use-public-share';
import type { PublicShareFileNode } from '@/types/documents';

type View = 'card' | 'list';

function fileGlyph(previewKind: string) {
  if (previewKind === 'image') return ImageIcon;
  if (previewKind === 'pdf') return FileText;
  return FileIcon;
}

export function ShareBrowser({ share }: { share: UsePublicShare }) {
  const [view, setView] = useState<View>('card');
  const [preview, setPreview] = useState<PublicShareFileNode | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const v = share.view;
  if (!v) return null;

  // Single-file share → just the file card + preview.
  if (v.kind === 'file' && v.file) {
    return (
      <div className="flex flex-col gap-4">
        <FilePanel file={v.file} share={share} onPreview={setPreview} />
        <PreviewModal preview={preview} share={share} onClose={() => setPreview(null)} />
      </div>
    );
  }

  const crumbs = v.breadcrumb;
  const empty = v.folders.length === 0 && v.files.length === 0;

  return (
    <div className="flex flex-col gap-3">
      {/* Toolbar: breadcrumb + view toggle + upload */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1 text-sm">
          {crumbs.map((c, i) => (
            <span key={c.id} className="inline-flex items-center gap-1">
              {i > 0 && <ChevronRight className="size-3.5 text-muted-foreground" />}
              <button
                type="button"
                className="rounded px-1.5 py-1 hover:bg-muted disabled:font-medium disabled:hover:bg-transparent"
                disabled={i === crumbs.length - 1}
                onClick={() => void share.navigate(c.id)}
              >
                {c.name}
              </button>
            </span>
          ))}
        </div>
        <div className="flex items-center rounded-md border p-0.5">
          <button
            type="button"
            aria-label="Card view"
            onClick={() => setView('card')}
            className={cn('rounded p-1.5', view === 'card' ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted')}
          >
            <LayoutGrid className="size-4" />
          </button>
          <button
            type="button"
            aria-label="List view"
            onClick={() => setView('list')}
            className={cn('rounded p-1.5', view === 'list' ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted')}
          >
            <List className="size-4" />
          </button>
        </div>
        {share.canUpload && (
          <>
            <input
              ref={fileInput}
              type="file"
              className="hidden"
              data-testid="share-upload-input"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void share.upload(f);
                e.target.value = '';
              }}
            />
            <Button size="sm" disabled={share.uploading} onClick={() => fileInput.current?.click()} data-testid="share-upload">
              {share.uploading ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
              Upload
            </Button>
          </>
        )}
      </div>

      {share.uploadError && (
        <Alert variant="destructive" appearance="light">
          <AlertIcon><FileIcon /></AlertIcon>
          <AlertTitle>{share.uploadError}</AlertTitle>
        </Alert>
      )}

      {empty ? (
        <p className="rounded-lg border bg-card py-12 text-center text-sm text-muted-foreground">
          This folder is empty.
        </p>
      ) : view === 'card' ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {v.folders.map((f) => (
            <button
              key={f.id}
              type="button"
              className="flex items-center gap-2 rounded-lg border bg-card p-3 text-left hover:bg-muted/50"
              onClick={() => void share.navigate(f.id)}
              data-testid="share-folder"
            >
              <Folder className="size-5 shrink-0 text-primary" />
              <span className="truncate text-sm font-medium">{f.name}</span>
            </button>
          ))}
          {v.files.map((file) => {
            const Glyph = fileGlyph(file.previewKind);
            return (
              <button
                key={file.id}
                type="button"
                className="flex flex-col gap-2 rounded-lg border bg-card p-3 text-left hover:bg-muted/50"
                onClick={() => setPreview(file)}
                data-testid="share-file"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <Glyph className="size-5 shrink-0 text-muted-foreground" />
                  <span className="truncate text-sm font-medium">{file.name}</span>
                </div>
                <span className="text-xs text-muted-foreground">{formatBytes(file.sizeBytes)}</span>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="divide-y rounded-lg border bg-card">
          {v.folders.map((f) => (
            <button
              key={f.id}
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted/50"
              onClick={() => void share.navigate(f.id)}
              data-testid="share-folder"
            >
              <Folder className="size-4 shrink-0 text-primary" />
              <span className="truncate font-medium">{f.name}</span>
            </button>
          ))}
          {v.files.map((file) => {
            const Glyph = fileGlyph(file.previewKind);
            return (
              <button
                key={file.id}
                type="button"
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted/50"
                onClick={() => setPreview(file)}
                data-testid="share-file"
              >
                <Glyph className="size-4 shrink-0 text-muted-foreground" />
                <span className="truncate font-medium">{file.name}</span>
                <span className="ml-auto shrink-0 text-xs text-muted-foreground">{formatBytes(file.sizeBytes)}</span>
              </button>
            );
          })}
        </div>
      )}

      <PreviewModal preview={preview} share={share} onClose={() => setPreview(null)} />
    </div>
  );
}

function FilePanel({
  file,
  share,
  onPreview,
}: {
  file: PublicShareFileNode;
  share: UsePublicShare;
  onPreview: (f: PublicShareFileNode) => void;
}) {
  const Glyph = fileGlyph(file.previewKind);
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-card p-3">
      <button
        type="button"
        className="flex min-w-0 items-center gap-2 text-left"
        onClick={() => file.previewKind !== 'none' && onPreview(file)}
      >
        <Glyph className="size-6 shrink-0 text-muted-foreground" />
        <div className="min-w-0">
          <p className="truncate font-medium">{file.name}</p>
          <p className="text-xs text-muted-foreground">{formatBytes(file.sizeBytes)}</p>
        </div>
      </button>
      <Button onClick={() => void share.download(file.id, file.name)} data-testid="share-download">
        <Download className="size-4" /> Download
      </Button>
    </div>
  );
}

function PreviewModal({
  preview,
  share,
  onClose,
}: {
  preview: PublicShareFileNode | null;
  share: UsePublicShare;
  onClose: () => void;
}) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let revoke: string | null = null;
    setUrl(null);
    if (preview && preview.previewKind !== 'none') {
      share
        .previewUrl(preview.id)
        .then((u) => {
          revoke = u;
          setUrl(u);
        })
        .catch(() => setUrl(null));
    }
    return () => {
      if (revoke) URL.revokeObjectURL(revoke);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview?.id]);

  if (!preview) return null;

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] w-[calc(100vw-2rem)] overflow-hidden p-0 sm:max-w-3xl">
        {/* pr-14 leaves room for the dialog's absolute close (X) button. */}
        <div className="flex items-center justify-between gap-2 border-b py-3 pl-4 pr-14">
          <DialogTitle className="truncate text-base">{preview.name}</DialogTitle>
          <Button size="sm" variant="outline" onClick={() => void share.download(preview.id, preview.name)}>
            <Download className="size-4" /> Download
          </Button>
        </div>
        <div className="flex max-h-[78vh] items-center justify-center overflow-auto bg-muted/30 p-3">
          {preview.previewKind === 'none' ? (
            <p className="py-16 text-center text-sm text-muted-foreground">
              No preview - download to open this file.
            </p>
          ) : !url ? (
            <div className="flex items-center justify-center py-20 text-muted-foreground">
              <Loader2 className="size-6 animate-spin" />
            </div>
          ) : preview.previewKind === 'image' ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={url} alt={preview.name} className="max-h-[74vh] w-auto object-contain" />
          ) : (
            // The blob is fetched from our own authed/sandboxed serve route; the
            // browser PDF viewer needs scripts so a restrictive `sandbox` would
            // render it blank - the bytes are already trusted at this point.
            <iframe title={preview.name} src={url} className="h-[74vh] w-full border-0" />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
