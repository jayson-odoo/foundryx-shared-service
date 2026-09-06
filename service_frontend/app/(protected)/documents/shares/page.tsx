'use client';

/**
 * Document shares oversight (plan sprint-3/05, D11 - the admin kill-switch).
 * Every active link across the tenant on the Resource shell (Active|Revoked
 * segments via the status-view toggle), row + bulk Revoke (bulk is typed-confirm
 * per ConfirmActionDialog). Gated `documents.share`.
 */
import { Fragment, useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { File as FileIcon, Folder, Slash } from 'lucide-react';
import type { ShareRow } from '@/types/documents';
import { useDatetime } from '@/hooks/use-datetime';
import { documentService } from '@/services/document-service';
import { Badge } from '@/components/ui/badge';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import {
  ResourceList,
  type ResourceListConfig,
} from '@/components/platform/resource-list';
import type { ResourceAction } from '@/components/platform/resource-list';

const stop = (e: React.MouseEvent) => e.stopPropagation();
const ACCESS_LABEL: Record<ShareRow['generalAccess'], string> = {
  restricted: 'Restricted',
  workspace: 'Workspace',
  public: 'Public',
};

export default function DocumentSharesPage() {
  const { formatDate } = useDatetime();

  const actions = useMemo<ResourceAction<ShareRow>[]>(
    () => [
      {
        id: 'revoke',
        label: 'Revoke',
        icon: Slash,
        tone: 'destructive',
        // Row surface ONLY - the bulk surface below is the typed-confirm
        // carve-out (fix round 2, S1). Grace-window deferred action
        // (sprint-4/23, T5, D2/D13) - no confirm dialog, no `run` (the
        // registered `document_shares.revoke` handler commits it
        // server-side).
        surfaces: { row: true },
        permission: 'documents.share',
        deferred: { actionKey: 'document_shares.revoke', entityType: 'document_share' },
      },
      {
        // Fix round 2, S1: the bulk revoke's typed confirmation is a
        // SHIPPED acceptance criterion (sprint-3/05 UAT AC-OVERSIGHT-03/
        // AC-UX-03) - round 1 dropped it migrating this action to
        // `deferred`, but a bulk selection has no per-row surface to host a
        // countdown, and bulk-revoking many links at once is exactly the
        // kind of "big blast radius" action D2/D13's own carve-out language
        // anticipates. Restored as the FOURTH typed-confirmation carve-out
        // (see `confirm-action-dialog.tsx` + `confirm-carve-outs.inventory.
        // test.ts`) - bulk only; the row action above stays on the
        // grace-window model.
        id: 'revoke-bulk',
        label: 'Revoke',
        icon: Slash,
        tone: 'destructive',
        surfaces: { bulk: true },
        permission: 'documents.share',
        confirm: {
          title: 'Revoke link(s)?',
          description:
            'Revoked links stop working immediately. This keeps the audit trail.',
          confirmLabel: 'Revoke',
          input: {
            expected: () => 'REVOKE',
            hint: () => 'Type REVOKE to confirm',
          },
        },
        run: async (rows, runtime) => {
          await documentService.revokeShares(rows.map((r) => r.id));
          runtime.reload();
        },
      },
    ],
    [],
  );

  const config = useMemo<ResourceListConfig<ShareRow>>(() => {
    const columns: ColumnDef<ShareRow>[] = [
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
        id: 'target',
        accessorFn: (row) => row.targetName ?? row.targetId,
        meta: { headerTitle: 'Target' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Target" column={column} />
        ),
        cell: ({ row }) => (
          <div className="flex min-w-0 items-center gap-2">
            {row.original.targetKind === 'folder' ? (
              <Folder className="size-4 shrink-0 text-muted-foreground" />
            ) : (
              <FileIcon className="size-4 shrink-0 text-muted-foreground" />
            )}
            <ClampedText
              text={row.original.targetName ?? '(deleted)'}
              lines={1}
              className="font-medium text-foreground"
            />
          </div>
        ),
        size: 240,
        enableSorting: false,
      },
      {
        id: 'access',
        accessorFn: (row) => row.generalAccess,
        meta: { headerTitle: 'General access' },
        header: ({ column }) => (
          <DataGridColumnHeader title="General access" column={column} />
        ),
        cell: ({ row }) => (
          <div className="flex items-center gap-1.5">
            <Badge variant="secondary" appearance="light" size="sm">
              {ACCESS_LABEL[row.original.generalAccess]}
            </Badge>
            {row.original.people.length > 0 && (
              <span className="text-xs text-muted-foreground">
                +{row.original.people.length}
              </span>
            )}
          </div>
        ),
        size: 170,
        enableSorting: true,
      },
      {
        id: 'capability',
        accessorFn: (row) => row.capability,
        meta: { headerTitle: 'Access' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Access" column={column} />
        ),
        cell: ({ row }) => (
          <span className="text-sm capitalize text-foreground">
            {row.original.capability}
          </span>
        ),
        size: 100,
        enableSorting: true,
      },
      {
        id: 'creator',
        accessorFn: (row) => row.createdByName ?? '',
        meta: { headerTitle: 'Created by' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Created by" column={column} />
        ),
        cell: ({ row }) => (
          <span className="text-sm text-foreground">
            {row.original.createdByName ?? '-'}
          </span>
        ),
        size: 160,
        enableSorting: false,
      },
      {
        id: 'expiry',
        accessorFn: (row) => row.expiresAt ?? '',
        meta: { headerTitle: 'Expiry' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Expiry" column={column} />
        ),
        cell: ({ row }) =>
          row.original.expiresAt ? (
            <span
              className={
                row.original.isExpired
                  ? 'text-sm text-warning'
                  : 'text-sm text-foreground'
              }
            >
              {formatDate(row.original.expiresAt)}
              {row.original.isExpired && ' (expired)'}
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">Never</span>
          ),
        size: 140,
        enableSorting: true,
      },
      {
        id: 'createdAt',
        accessorFn: (row) => row.createdAt,
        meta: { headerTitle: 'Created' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Created" column={column} />
        ),
        cell: ({ row }) => (
          <span className="text-sm text-foreground">
            {formatDate(row.original.createdAt)}
          </span>
        ),
        size: 140,
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
      viewKey: 'documents.shares',
      getRowId: (row) => row.id,
      // No per-row detail page - actions (Revoke) live in the row menu.
      rowHref: () => '#',
      fetcher: (query) =>
        documentService.listShares(
          query,
          query.statusView === 'trashed' ? 'revoked' : 'active',
        ),
      exporter: (query, columns) =>
        documentService.exportShares(
          query,
          columns,
          query.statusView === 'trashed' ? 'revoked' : 'active',
        ),
      searchPlaceholder: 'Search links…',
      searchHints: ['General access', 'Role'],
      defaultSort: { id: 'createdAt', desc: true },
      exportFilename: 'document-shares',
      enableStatusViews: true,
      statusViewLabels: { active: 'Active', trashed: 'Revoked' },
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'target', label: 'Target' },
        { id: 'access', label: 'General access' },
        { id: 'capability', label: 'Access' },
        { id: 'creator', label: 'Created by' },
        { id: 'expiry', label: 'Expiry' },
        { id: 'createdAt', label: 'Created' },
      ],
      actions,
    };
  }, [actions, formatDate]);

  return (
    <RequirePermission permission="documents.share">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
