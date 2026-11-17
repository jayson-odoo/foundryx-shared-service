'use client';

import { useMemo, useState } from 'react';
import { LoaderCircleIcon, UserMinus } from 'lucide-react';
import type { ColumnDef } from '@tanstack/react-table';
import { Button } from '@/components/ui/button';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Card, CardContent } from '@/components/ui/card';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { ResourceList, type ResourceAction, type ResourceListConfig } from '@/components/platform/resource-list';
import { SearchSelect } from '@/components/platform/search-select';
import { toCsv } from '@/lib/csv';
import { toast } from '@/lib/toast';
import { useContactPicker } from '@/hooks/use-contact-picker';
import { useDatetime } from '@/hooks/use-datetime';
import { useIdeaFollowers } from '@/hooks/use-idea-followers';
import { useWorkspaceId } from '@/hooks/use-workspace-id';
import type { ListQuery, ListResult } from '@/types/resource';
import type { IdeaFollower } from '@/types/ideation';

const stop = (e: React.MouseEvent) => e.stopPropagation();

/** Sort keys per column (the list is the item's whole follower set, sorted here). */
const SORT_KEYS: Record<string, (r: IdeaFollower) => string> = {
  name: (r) => (r.name ?? '').toLowerCase(),
  phone: (r) => r.phone ?? '',
  addedBy: (r) => (r.addedByStaff ? 'staff' : 'themselves'),
  since: (r) => r.createdAt ?? '',
};

export interface IdeaFollowersTabProps {
  ideaId: string;
  /** Staff may add / remove (``ideation.triage.manage``). */
  canManage: boolean;
}

/** "Add follower": the shared server-searched contact picker. */
function AddFollowerDialog({
  open,
  onClose,
  onAdd,
}: {
  open: boolean;
  onClose: () => void;
  onAdd: (contactId: string) => Promise<void>;
}) {
  const { workspaceId } = useWorkspaceId();
  const [contactId, setContactId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { options, setQuery } = useContactPicker(workspaceId, contactId ? [contactId] : []);
  const save = async () => {
    if (!contactId) return;
    setBusy(true);
    setError(null);
    try {
      await onAdd(contactId);
      setContactId(null);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not add the follower.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent className="max-w-md" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Add follower</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-2">
          <SearchSelect
            options={options}
            value={contactId}
            onChange={(v) => setContactId(v || null)}
            onQueryChange={setQuery}
            ariaLabel="Contact"
            placeholder="Contact"
            className="w-full"
          />
          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={!contactId || busy}>
            {busy && <LoaderCircleIcon className="size-3.5 animate-spin" />}
            Add
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Followers of a feedback item (lane FEEDBACK-SUBSCRIBE R9) on the shared
 * `ResourceList` (a clone of the "Merged from" tab): they get the same
 * WhatsApp status update as the submitter. Staff add one through the contact
 * picker and remove through the row / bulk actions.
 */
export function IdeaFollowersTab({ ideaId, canManage }: IdeaFollowersTabProps) {
  const { followers, error, add, remove, reload } = useIdeaFollowers(ideaId);
  const { formatDmyDate } = useDatetime();
  const [adding, setAdding] = useState(false);

  const config = useMemo<ResourceListConfig<IdeaFollower>>(() => {
    const rows = followers ?? [];

    const actions: ResourceAction<IdeaFollower>[] = canManage
      ? [
          {
            id: 'remove-follower',
            label: 'Remove',
            icon: UserMinus,
            surfaces: { row: true, form: false, bulk: true },
            isVisible: () => true,
            run: async (selected) => {
              await remove(selected.map((r) => r.contactId));
              toast.success(selected.length === 1 ? 'Follower removed.' : 'Followers removed.');
            },
          },
        ]
      : [];

    const columns: ColumnDef<IdeaFollower>[] = [
      {
        id: 'name',
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.name ?? '-'} lines={1} />,
        size: 220,
      },
      {
        id: 'phone',
        meta: { headerTitle: 'Phone' },
        header: ({ column }) => <DataGridColumnHeader title="Phone" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.phone ?? '-'}</span>,
        size: 160,
      },
      {
        id: 'addedBy',
        meta: { headerTitle: 'Added by' },
        header: ({ column }) => <DataGridColumnHeader title="Added by" column={column} />,
        cell: ({ row }) => <span>{row.original.addedByStaff ? 'Staff' : 'Themselves'}</span>,
        size: 120,
      },
      {
        id: 'since',
        meta: { headerTitle: 'Following since' },
        header: ({ column }) => <DataGridColumnHeader title="Following since" column={column} />,
        cell: ({ row }) => <span>{row.original.createdAt ? formatDmyDate(row.original.createdAt) : '-'}</span>,
        size: 140,
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
        size: 56,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
    ];

    const fetcher = async (query: ListQuery): Promise<ListResult<IdeaFollower>> => {
      let data = rows;
      if (query.search) {
        const s = query.search.toLowerCase();
        data = data.filter(
          (r) => (r.name ?? '').toLowerCase().includes(s) || (r.phone ?? '').toLowerCase().includes(s),
        );
      }
      if (query.sort) {
        const key = SORT_KEYS[query.sort.id];
        if (key) {
          const dir = query.sort.desc ? -1 : 1;
          data = [...data].sort((a, b) => dir * key(a).localeCompare(key(b)));
        }
      }
      const start = query.page * query.pageSize;
      return { data: data.slice(start, start + query.pageSize), total: data.length, page: query.page };
    };

    const exporter = async (query: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...query, page: 0, pageSize: 10_000 });
      return toCsv(
        ['Name', 'Phone', 'Added by', 'Following since'],
        data.map((r) => [
          r.name ?? '',
          r.phone ?? '',
          r.addedByStaff ? 'Staff' : 'Themselves',
          r.createdAt ? formatDmyDate(r.createdAt) : '',
        ]),
      );
    };

    return {
      viewKey: 'ideation.idea.followers',
      getRowId: (row) => row.contactId,
      // No detail page: a follower row opens nothing.
      rowHref: () => '#',
      fetcher,
      exporter,
      searchPlaceholder: 'Search followers…',
      searchHints: ['Name', 'Phone'],
      enableStatusViews: false,
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'name', label: 'Name' },
        { id: 'phone', label: 'Phone' },
        { id: 'addedBy', label: 'Added by' },
        { id: 'since', label: 'Following since' },
      ],
      actions,
      ...(canManage ? { onCreate: () => setAdding(true) } : {}),
    };
  }, [followers, canManage, remove, formatDmyDate]);

  if (followers === null) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12 text-muted-foreground">
          <LoaderCircleIcon className="size-5 animate-spin" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="py-4">
        {error && (
          <div className="mb-2 flex items-center gap-2 text-sm text-destructive" role="alert">
            <span>{error}</span>
            <Button mode="link" size="sm" onClick={reload}>
              Try again
            </Button>
          </div>
        )}
        {/* Keyed on the rows so an add / remove refetches the embedded list. */}
        <ResourceList key={followers.map((f) => f.contactId).join(',')} config={config} hideHeader />
        <AddFollowerDialog
          open={adding}
          onClose={() => setAdding(false)}
          onAdd={async (id) => {
            await add(id);
            toast.success('Follower added.');
          }}
        />
      </CardContent>
    </Card>
  );
}
