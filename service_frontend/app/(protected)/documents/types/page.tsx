'use client';

import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { Pencil, Trash2 } from 'lucide-react';
import type { AttachmentTypeRow } from '@/types/documents';
import { documentService } from '@/services/document-service';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import {
  ResourceList,
  type ResourceListConfig,
} from '@/components/platform/resource-list';
import type { ResourceAction } from '@/components/platform/resource-list';

const TYPES_PATH = '/documents/types';
const stop = (e: React.MouseEvent) => e.stopPropagation();

export default function DocumentTypesPage() {
  const router = useRouter();
  const params = useSearchParams();
  const editId = params.get('edit');

  const [reloadToken, setReloadToken] = useState(0);

  const openEditor = useCallback(
    (id: string | 'new') => router.push(`${TYPES_PATH}?edit=${id}`),
    [router],
  );
  const closeEditor = useCallback(() => router.push(TYPES_PATH), [router]);

  const actions = useMemo<ResourceAction<AttachmentTypeRow>[]>(
    () => [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        surfaces: { row: true, form: true },
        permission: 'documents.configure',
        run: (rows) => openEditor(rows[0].id),
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        surfaces: { row: true, bulk: true },
        permission: 'documents.configure',
        confirm: {
          title: 'Delete type?',
          description: 'Files keep their bytes; they just lose this category.',
          confirmLabel: 'Delete',
        },
        run: async (rows, runtime) => {
          await Promise.all(rows.map((r) => documentService.deleteType(r.id)));
          runtime.reload();
        },
      },
    ],
    [openEditor],
  );

  const config = useMemo<ResourceListConfig<AttachmentTypeRow>>(() => {
    const columns: ColumnDef<AttachmentTypeRow>[] = [
      {
        id: 'select',
        meta: { reorderable: false },
        header: () => (
          <div onClick={stop}>
            <DataGridTableRowSelectAll />
          </div>
        ),
        cell: ({ row }) => (
          <div onClick={stop}>
            <DataGridTableRowSelect row={row} />
          </div>
        ),
        size: 48,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
      {
        id: 'name',
        accessorFn: (row) => row.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Name" column={column} />
        ),
        cell: ({ row }) => (
          <div className="flex flex-col">
            <span className="font-medium leading-tight text-foreground">
              {row.original.name}
            </span>
            <ClampedText
              text={row.original.description ?? ''}
              lines={1}
              className="text-xs text-muted-foreground"
            />
          </div>
        ),
        size: 240,
        enableSorting: true,
      },
      {
        id: 'allowedExts',
        accessorFn: (row) => row.allowedExts.join(', '),
        meta: { headerTitle: 'Allowed types' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Allowed types" column={column} />
        ),
        cell: ({ row }) =>
          row.original.allowedExts.length === 0 ? (
            <span className="text-xs text-muted-foreground">Any</span>
          ) : (
            <div className="flex flex-wrap gap-1">
              {row.original.allowedExts.map((e) => (
                <Badge key={e} variant="secondary" appearance="light" size="sm">
                  .{e}
                </Badge>
              ))}
            </div>
          ),
        size: 220,
        enableSorting: false,
      },
      {
        id: 'maxMb',
        accessorFn: (row) => row.maxMb,
        meta: { headerTitle: 'Max size' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Max size" column={column} />
        ),
        cell: ({ row }) => (
          <span className="text-sm text-foreground">
            {row.original.maxMb != null
              ? `${row.original.maxMb} MB`
              : 'Tenant default'}
          </span>
        ),
        size: 140,
        enableSorting: true,
      },
      {
        id: 'fileCount',
        accessorFn: (row) => row.fileCount,
        meta: { headerTitle: 'Files' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Files" column={column} />
        ),
        cell: ({ row }) => (
          <span className="text-sm text-foreground">
            {row.original.fileCount}
          </span>
        ),
        size: 90,
        enableSorting: true,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => (
          <div onClick={stop} className="flex justify-end">
            <ActionMenu
              actions={actions}
              rows={[row.original]}
              runtime={{ reload: table.options.meta?.reload ?? (() => {}) }}
              surface="row"
            />
          </div>
        ),
        size: 60,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
    ];

    return {
      viewKey: 'documents.types',
      getRowId: (row) => row.id,
      rowHref: (row) => `${TYPES_PATH}?edit=${row.id}`,
      fetcher: (query) => documentService.listTypes(query),
      exporter: (query, columns) => documentService.exportTypes(query, columns),
      searchPlaceholder: 'Search types…',
      searchHints: ['Name', 'Description'],
      defaultSort: { id: 'name', desc: false },
      exportFilename: 'document-types',
      createLabel: 'New type',
      createPermission: 'documents.configure',
      onCreate: () => openEditor('new'),
      enableStatusViews: false,
      columns,
      filterFields: [{ field: 'name', label: 'Name', type: 'text' }],
      exportColumns: [
        { id: 'name', label: 'Name' },
        { id: 'description', label: 'Description' },
        { id: 'allowedExts', label: 'Allowed types' },
        { id: 'maxMb', label: 'Max MB' },
        { id: 'fileCount', label: 'Files' },
      ],
      actions,
    };
  }, [actions, openEditor]);

  return (
    <RequirePermission permission="documents.configure">
      <Fragment>
        <Container width="fluid">
          <ResourceList key={reloadToken} config={config} />
        </Container>
        {editId && (
          <TypeFormDialog
            typeId={editId === 'new' ? null : editId}
            onClose={closeEditor}
            onSaved={() => {
              setReloadToken((t) => t + 1);
              closeEditor();
            }}
          />
        )}
      </Fragment>
    </RequirePermission>
  );
}

// ── Create / edit dialog (trivial entity → modal, house-sanctioned) ─────────

function TypeFormDialog({
  typeId,
  onClose,
  onSaved,
}: {
  typeId: string | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [exts, setExts] = useState('');
  const [maxMb, setMaxMb] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(!!typeId);

  useEffect(() => {
    if (!typeId) return;
    setLoading(true);
    documentService
      .getType(typeId)
      .then((t) => {
        setName(t.name);
        setDescription(t.description ?? '');
        setExts(t.allowedExts.join(', '));
        setMaxMb(t.maxMb != null ? String(t.maxMb) : '');
      })
      .finally(() => setLoading(false));
  }, [typeId]);

  const save = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    const payload = {
      name: name.trim(),
      description: description.trim() || null,
      allowedExts: exts
        .split(',')
        .map((e) => e.trim().replace(/^\./, '').toLowerCase())
        .filter(Boolean),
      maxMb: maxMb.trim() ? Number(maxMb) : null,
    };
    try {
      if (typeId) await documentService.updateType(typeId, payload);
      else await documentService.createType(payload);
      onSaved();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{typeId ? 'Edit type' : 'New type'}</DialogTitle>
        </DialogHeader>
        {loading ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Loading…
          </p>
        ) : (
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="type-name">Name *</Label>
              <Input
                id="type-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoFocus
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="type-desc">Description</Label>
              <Input
                id="type-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="type-exts">Allowed extensions</Label>
              <Input
                id="type-exts"
                value={exts}
                placeholder="pdf, docx, xlsx (blank = any)"
                onChange={(e) => setExts(e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="type-max">Max file size (MB)</Label>
              <Input
                id="type-max"
                type="number"
                min={1}
                value={maxMb}
                placeholder="Blank = tenant default"
                onChange={(e) => setMaxMb(e.target.value)}
              />
            </div>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            onClick={() => void save()}
            disabled={!name.trim() || busy || loading}
          >
            {typeId ? 'Save type' : 'Create type'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
