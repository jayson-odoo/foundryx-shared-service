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
import { ResourceList, type ResourceAction, type ResourceListConfig } from '@/components/platform/resource-list';
import { SearchSelect } from '@/components/platform/search-select';
import { toCsv } from '@/lib/csv';
import { toast } from '@/lib/toast';
import { useContactPicker } from '@/hooks/use-contact-picker';
import { useDatetime } from '@/hooks/use-datetime';
import { useIdeaFollowers } from '@/hooks/use-idea-followers';
import { useWorkspaceId } from '@/hooks/use-workspace-id';
import { matchesFilterGroup, type ClientFilterValue } from '@/lib/client-filter';
import type { FilterFieldDef, ListQuery, ListResult } from '@/types/resource';
import type { IdeaFollower } from '@/types/ideation';

/** Sort keys per column (the list is the item's whole follower set, sorted here). */
const SORT_KEYS: Record<string, (r: IdeaFollower) => string> = {
  name: (r) => (r.name ?? '').toLowerCase(),
  phone: (r) => r.phone ?? '',
  addedBy: (r) => (r.addedByStaff ? 'staff' : 'themselves'),
  since: (r) => r.createdAt ?? '',
};

const ADDED_BY = (r: IdeaFollower) => (r.addedByStaff ? 'Staff' : 'Themselves');

/** Filter values per declared field (enum values are the raw keys). */
function filterValue(r: IdeaFollower, field: string): ClientFilterValue {
  if (field === 'name') return r.name;
  if (field === 'phone') return r.phone;
  if (field === 'addedBy') return r.addedByStaff ? 'staff' : 'self';
  if (field === 'since') return r.createdAt;
  return null;
}

export const FOLLOWER_FILTER_FIELDS: FilterFieldDef[] = [
  { field: 'name', label: 'Name', type: 'text' },
  { field: 'phone', label: 'Phone', type: 'text' },
  {
    field: 'addedBy',
    label: 'Added by',
    type: 'enum',
    options: [
      { label: 'Staff', value: 'staff' },
      { label: 'Themselves', value: 'self' },
    ],
  },
  { field: 'since', label: 'Following since', type: 'date' },
];

/** One page of the (small, fully loaded) follower set: search, filter, sort. */
export function followersPage(rows: IdeaFollower[], query: ListQuery): ListResult<IdeaFollower> {
  let data = rows;
  if (query.search) {
    const s = query.search.toLowerCase();
    data = data.filter((r) => (r.name ?? '').toLowerCase().includes(s) || (r.phone ?? '').toLowerCase().includes(s));
  }
  data = data.filter((r) => matchesFilterGroup(r, query.filter, filterValue));
  if (query.sort) {
    const key = SORT_KEYS[query.sort.id];
    if (key) {
      const dir = query.sort.desc ? -1 : 1;
      data = [...data].sort((a, b) => dir * key(a).localeCompare(key(b)));
    }
  }
  const start = query.page * query.pageSize;
  return { data: data.slice(start, start + query.pageSize), total: data.length, page: query.page };
}

const EXPORT_COLUMNS = [
  { id: 'name', label: 'Name', value: (r: IdeaFollower) => r.name ?? '' },
  { id: 'phone', label: 'Phone', value: (r: IdeaFollower) => r.phone ?? '' },
  { id: 'addedBy', label: 'Added by', value: ADDED_BY },
] as const;

/** CSV of exactly the ticked columns (in screen order) and, when rows are
 * ticked, only those rows. */
export function followersCsv(
  rows: IdeaFollower[],
  columns: string[],
  ids: string[] | undefined,
  formatDate: (iso: string) => string,
): string {
  const all = [
    ...EXPORT_COLUMNS,
    { id: 'since', label: 'Following since', value: (r: IdeaFollower) => (r.createdAt ? formatDate(r.createdAt) : '') },
  ];
  const picked = all.filter((c) => columns.includes(c.id));
  const data = ids && ids.length ? rows.filter((r) => ids.includes(r.contactId)) : rows;
  return toCsv(
    picked.map((c) => c.label),
    data.map((r) => picked.map((c) => c.value(r))),
  );
}

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
  const [query, setQueryText] = useState('');
  const picker = useContactPicker(workspaceId, contactId ? [contactId] : []);
  // The shared picker keeps every contact it ever loaded (so a chosen label
  // never disappears); typing must still narrow what is offered, by name or
  // phone (crew pass 70e96f2b). The chosen contact always stays listed.
  const options = useMemo(() => {
    const q = query.trim().toLowerCase();
    const digits = q.replace(/\D/g, '');
    if (!q) return picker.options;
    return picker.options.filter(
      (o) =>
        o.value === contactId ||
        o.label.toLowerCase().includes(q) ||
        (digits.length > 0 && o.label.replace(/\D/g, '').includes(digits)),
    );
  }, [picker.options, query, contactId]);
  const setQuery = (q: string) => {
    setQueryText(q);
    picker.setQuery(q);
  };
  // Every open starts clean: no pick, no refusal, the full list (crew pass
  // 41998794: a closed dialog kept its last search filter).
  const close = () => {
    setContactId(null);
    setError(null);
    setQuery('');
    onClose();
  };
  const save = async () => {
    if (!contactId) return;
    setBusy(true);
    setError(null);
    try {
      await onAdd(contactId);
      close();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not add the follower.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={(o) => !o && !busy && close()}>
      <DialogContent className="max-w-md" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Add follower</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-2">
          <SearchSelect
            options={options}
            value={contactId}
            onChange={(v) => {
              setContactId(v || null);
              // A refusal belongs to the contact it was about.
              setError(null);
            }}
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
          <Button variant="outline" onClick={close} disabled={busy}>
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
 * `ResourceList`: they get the same WhatsApp status update as the submitter.
 * A row opens the contact; right-click a row (or tick rows) to remove; the
 * toolbar Create adds one through the contact picker.
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
        accessorFn: (r) => r.name ?? '',
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.name ?? '-'} lines={1} />,
        size: 220,
      },
      {
        id: 'phone',
        accessorFn: (r) => r.phone ?? '',
        meta: { headerTitle: 'Phone' },
        header: ({ column }) => <DataGridColumnHeader title="Phone" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.phone ?? '-'}</span>,
        size: 160,
      },
      {
        id: 'addedBy',
        accessorFn: ADDED_BY,
        meta: { headerTitle: 'Added by' },
        header: ({ column }) => <DataGridColumnHeader title="Added by" column={column} />,
        cell: ({ row }) => <span>{ADDED_BY(row.original)}</span>,
        size: 120,
      },
      {
        id: 'since',
        accessorFn: (r) => r.createdAt ?? '',
        meta: { headerTitle: 'Following since' },
        header: ({ column }) => <DataGridColumnHeader title="Following since" column={column} />,
        cell: ({ row }) => <span>{row.original.createdAt ? formatDmyDate(row.original.createdAt) : '-'}</span>,
        size: 140,
      },
    ];

    return {
      viewKey: 'ideation.idea.followers',
      getRowId: (row) => row.contactId,
      getEntityId: (row) => row.contactId,
      // A row opens the follower's contact record.
      rowHref: (row) => `/omnichannel/contacts/${encodeURIComponent(row.contactId)}`,
      fetcher: async (query: ListQuery) => followersPage(rows, query),
      exporter: async (_query, cols, ids) => followersCsv(rows, cols, ids, formatDmyDate),
      exportFilename: 'followers',
      searchPlaceholder: 'Search followers…',
      searchHints: ['Name', 'Phone'],
      enableStatusViews: false,
      columns,
      filterFields: FOLLOWER_FILTER_FIELDS,
      exportColumns: [
        { id: 'name', label: 'Name' },
        { id: 'phone', label: 'Phone' },
        { id: 'addedBy', label: 'Added by' },
        { id: 'since', label: 'Following since' },
      ],
      actions,
      ...(canManage ? { onCreate: () => setAdding(true), createVariant: 'outline' as const } : {}),
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
        <ResourceList
          key={followers.map((f) => `${f.contactId}:${f.addedByStaff ? 's' : 't'}`).join(',')}
          config={config}
          hideHeader
        />
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
