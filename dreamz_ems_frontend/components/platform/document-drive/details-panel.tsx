'use client';

import { useEffect, useState } from 'react';
import { Folder, History, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useDatetime } from '@/hooks/use-datetime';
import { documentService } from '@/services/document-service';
import type { FileRow, FileVersionRow, FolderRow } from '@/types/documents';
import { fileIcon, formatBytes } from './lib';

export type DetailsTarget =
  | { kind: 'folder'; folder: FolderRow }
  | { kind: 'file'; file: FileRow };

export interface DetailsPanelProps {
  target: DetailsTarget;
  onClose: () => void;
}

/** Right-hand inspector (sprint-3/04b): metadata + (files) version history. */
export function DetailsPanel({ target, onClose }: DetailsPanelProps) {
  const { formatDateTime } = useDatetime();
  const [versions, setVersions] = useState<FileVersionRow[] | null>(null);

  const fileId = target.kind === 'file' ? target.file.id : null;
  useEffect(() => {
    if (!fileId) {
      setVersions(null);
      return;
    }
    setVersions(null);
    documentService
      .fileVersions(fileId)
      .then(setVersions)
      .catch(() => setVersions([]));
  }, [fileId]);

  const name = target.kind === 'folder' ? target.folder.name : target.file.name;
  const Icon = target.kind === 'folder' ? Folder : fileIcon(target.file.name);

  return (
    <aside className="shrink-0 lg:w-72">
      <div className="rounded-lg border bg-card lg:sticky lg:top-4">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <span className="text-sm font-medium">Details</span>
          <Button variant="ghost" size="icon" className="size-7" onClick={onClose} aria-label="Close details">
            <X className="size-4" />
          </Button>
        </div>
        <ScrollArea className="max-h-[60vh] lg:max-h-[calc(100vh-12rem)]">
          <div className="space-y-4 p-4">
            <div className="flex flex-col items-center gap-2 text-center">
              <Icon
                className={target.kind === 'folder' ? 'size-12 text-primary' : 'size-12 text-muted-foreground'}
              />
              <p className="break-words text-sm font-medium" title={name}>
                {name}
              </p>
            </div>

            <dl className="space-y-2 text-sm">
              <Row label="Type">
                {target.kind === 'folder'
                  ? 'Folder'
                  : target.file.attachmentTypeName ??
                    (target.file.name.includes('.')
                      ? target.file.name.split('.').pop()!.toUpperCase()
                      : 'File')}
              </Row>
              {target.kind === 'folder' ? (
                <Row label="Items">{target.folder.folderCount + target.folder.fileCount}</Row>
              ) : (
                <Row label="Size">{formatBytes(target.file.currentVersion.sizeBytes)}</Row>
              )}
              {target.kind === 'file' && (
                <Row label="Versions">{target.file.versionCount}</Row>
              )}
              <Row label="Created">
                {formatDateTime(target.kind === 'folder' ? target.folder.createdAt : target.file.createdAt)}
              </Row>
              <Row label="Modified">
                {formatDateTime(target.kind === 'folder' ? target.folder.updatedAt : target.file.updatedAt)}
              </Row>
              {target.kind === 'file' && target.file.createdByName && (
                <Row label="Owner">{target.file.createdByName}</Row>
              )}
            </dl>

            {target.kind === 'file' && (
              <div>
                <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <History className="size-3.5" /> Version history
                </div>
                {versions === null ? (
                  <p className="text-xs text-muted-foreground">Loading…</p>
                ) : (
                  <ul className="space-y-2">
                    {versions.map((v) => (
                      <li key={v.id} className="rounded-md border px-2.5 py-2 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="font-medium">v{v.ordinal}</span>
                          <span className="text-muted-foreground">{formatBytes(v.sizeBytes)}</span>
                        </div>
                        <div className="text-muted-foreground">{formatDateTime(v.createdAt)}</div>
                        {v.uploadedByName && (
                          <div className="text-muted-foreground">{v.uploadedByName}</div>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        </ScrollArea>
      </div>
    </aside>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right font-medium">{children}</dd>
    </div>
  );
}
