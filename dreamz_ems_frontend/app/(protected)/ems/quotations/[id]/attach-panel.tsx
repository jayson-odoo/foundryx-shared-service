'use client';

/** Document-attach panel — consumes the core /documents/file-links seam to link
 * Drive files to a domain entity (first consumer: quotations). Lists current
 * links, attaches via a Drive folder picker, removes a link. */
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { ChevronRight, FileText, Folder, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ResourceList } from '@/components/platform/resource-list';
import { embeddedListConfig } from '@/components/platform/resource-list/embedded-list-config';
import { useCan } from '@/hooks/use-can';
import { emsService } from '@/services/ems-service';
import { documentService } from '@/services/document-service';
import type { FileLink } from '@/types/ems';

interface LinkRow {
  id: string;
  fileId: string;
  name: string;
}

export function AttachPanel({ entityType, entityId }: { entityType: string; entityId: string }) {
  const { can } = useCan();
  const manage = can('documents.manage');
  const [picking, setPicking] = useState(false);
  const [nonce, setNonce] = useState(0);

  const config = useMemo(
    () =>
      embeddedListConfig<LinkRow>({
        viewKey: 'quotation_documents',
        getRowId: (r) => r.id,
        rowHref: () => '#',
        searchPlaceholder: 'Search documents…',
        createLabel: 'Attach a file',
        onCreate: manage ? () => setPicking(true) : undefined,
        createPermission: 'documents.manage',
        fetcher: async () => {
          const [links, root] = await Promise.all([
            emsService.listFileLinks(entityType, entityId),
            documentService.listFolder(null).catch(() => ({ files: [] as { id: string; name: string }[] })),
          ]);
          const names = Object.fromEntries(root.files.map((f) => [f.id, f.name]));
          const data: LinkRow[] = links.map((l: FileLink) => ({ id: l.id, fileId: l.fileId, name: names[l.fileId] ?? 'Document' }));
          return { data, total: data.length, page: 0 };
        },
        columns: [
          {
            id: 'name',
            accessorKey: 'name',
            header: 'Document',
            cell: ({ row }) => (
              <span className="flex items-center gap-2">
                <FileText className="size-4 text-muted-foreground" /> {row.original.name}
              </span>
            ),
          },
        ],
        actions: manage
          ? [
              {
                id: 'remove',
                label: 'Remove',
                icon: Trash2,
                surfaces: { row: true, form: false, bulk: false },
                permission: 'documents.manage',
                run: async (_rows: LinkRow[], runtime: { reload: () => void }) => {
                  const r = _rows[0];
                  try {
                    await emsService.detachFile(r.id);
                    runtime.reload();
                  } catch (e) {
                    toast.error(e instanceof Error ? e.message : 'Could not remove.');
                  }
                },
              },
            ]
          : [],
      }),
    [entityType, entityId, manage],
  );

  return (
    <div className="py-2">
      <ResourceList key={nonce} config={config} />
      {picking && (
        <FilePickerDialog
          entityType={entityType}
          entityId={entityId}
          onClose={() => setPicking(false)}
          onAttached={() => {
            setPicking(false);
            setNonce((n) => n + 1);
          }}
        />
      )}
    </div>
  );
}

interface PickerRow {
  id: string;
  name: string;
}

function FilePickerDialog({
  entityType,
  entityId,
  onClose,
  onAttached,
}: {
  entityType: string;
  entityId: string;
  onClose: () => void;
  onAttached: (fileId: string, fileName: string) => void;
}) {
  const [folderId, setFolderId] = useState<string | null>(null);
  const [folders, setFolders] = useState<PickerRow[]>([]);
  const [files, setFiles] = useState<PickerRow[]>([]);
  const [crumbs, setCrumbs] = useState<{ id: string | null; name: string }[]>([{ id: null, name: 'Drive' }]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    documentService
      .listFolder(folderId)
      .then((l) => {
        setFolders(l.folders.map((f) => ({ id: f.id, name: f.name })));
        setFiles(l.files.map((f) => ({ id: f.id, name: f.name })));
      })
      .catch(() => {
        setFolders([]);
        setFiles([]);
      });
  }, [folderId]);

  const enter = (f: PickerRow) => {
    setFolderId(f.id);
    setCrumbs((prev) => [...prev, { id: f.id, name: f.name }]);
  };
  const goTo = (idx: number) => {
    const c = crumbs[idx];
    setFolderId(c.id);
    setCrumbs((prev) => prev.slice(0, idx + 1));
  };

  const attach = async (f: PickerRow) => {
    setBusy(true);
    try {
      await emsService.attachFile(entityType, entityId, f.id);
      toast.success('Document attached.');
      onAttached(f.id, f.name);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not attach.');
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Attach a document</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-3">
          <div className="flex flex-wrap items-center gap-1 text-sm text-muted-foreground">
            {crumbs.map((c, i) => (
              <span key={`${c.id ?? 'root'}`} className="flex items-center gap-1">
                {i > 0 && <ChevronRight className="size-3" />}
                <button type="button" className="hover:text-foreground" onClick={() => goTo(i)}>
                  {c.name}
                </button>
              </span>
            ))}
          </div>
          <ul className="max-h-80 divide-y divide-border overflow-y-auto rounded-lg border border-border">
            {folders.length === 0 && files.length === 0 && (
              <li className="px-4 py-6 text-center text-sm text-muted-foreground">This folder is empty.</li>
            )}
            {folders.map((f) => (
              <li key={f.id}>
                <button
                  type="button"
                  className="flex w-full items-center gap-3 px-4 py-2.5 text-start text-sm hover:bg-accent"
                  onClick={() => enter(f)}
                >
                  <Folder className="size-4 text-muted-foreground" />
                  <span className="flex-1">{f.name}</span>
                  <ChevronRight className="size-4 text-muted-foreground" />
                </button>
              </li>
            ))}
            {files.map((f) => (
              <li key={f.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <FileText className="size-4 text-muted-foreground" />
                <span className="flex-1">{f.name}</span>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => void attach(f)}>
                  Attach
                </Button>
              </li>
            ))}
          </ul>
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
