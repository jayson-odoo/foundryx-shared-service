'use client';

/**
 * Contacts list config (plan 26, D-A2-2) - a clone of
 * `use-users-list-config.tsx` (the Resource-shell reference). Columns Name,
 * Phone, Email, Lifecycle, Tags, Assignee, Channel, Last message, Created,
 * plus the leading select and trailing row "…" columns.
 */
import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { DataGridTableRowSelect, DataGridTableRowSelectAll } from '@/components/ui/data-grid-table';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import type { LifecycleStageOption } from '@/hooks/use-contact-lifecycle-stages';
import { contactService } from '@/services/contact-service';
import { ExportPendingError } from '@/lib/service-errors';
import type {
  ContactField,
  ContactListItem,
  ContactSegment,
  ContactTag,
  WorkspaceMember,
} from '@/types/omnichannel';
import type { FilterFieldDef, FilterFieldType, FilterGroup } from '@/types/resource';
import { ContactChannelsCell } from './contact-channels-cell';
import { ContactLifecycleCell } from './contact-lifecycle-cell';
import { ContactTagsCell } from './contact-tags-cell';
import { contactFormPath, contactNewPath } from './paths';
import { segmentOptions } from './segment-picker';
import { exportPendingToast } from './export-pending-toast';

const stop = (e: React.MouseEvent) => e.stopPropagation();

const PRIORITY_OPTIONS = [
  { label: 'Low', value: 'LOW' },
  { label: 'Medium', value: 'MEDIUM' },
  { label: 'High', value: 'HIGH' },
  { label: 'Urgent', value: 'URGENT' },
];

/** `customFields.<key>` filter type derived from the field's registered type
 *  (AC-CTM-04) - the shell only knows text/enum/date/bool, so `number`/`time`
 *  map to the closest usable operator set (documented deviation, no numeric
 *  range or time-of-day filter in this slice). */
function customFieldFilterType(field: ContactField): FilterFieldType {
  switch (field.type) {
    case 'list':
      return 'enum';
    case 'checkbox':
      return 'bool';
    case 'date':
      return 'date';
    default:
      return 'text';
  }
}

export interface UseContactsListConfigParams {
  workspaceId: string;
  segments: ContactSegment[];
  tags: ContactTag[];
  fields: ContactField[];
  stages: LifecycleStageOption[];
  members: WorkspaceMember[];
  channelTypeOptions: { label: string; value: string }[];
  actions: ResourceAction<ContactListItem>[];
  onFilterChange: (filter: FilterGroup | null) => void;
}

export function useContactsListConfig({
  workspaceId,
  segments,
  tags,
  fields,
  stages,
  members,
  channelTypeOptions,
  actions,
  onFilterChange,
}: UseContactsListConfigParams): ResourceListConfig<ContactListItem> {
  const { formatDate, formatDateTime } = useDatetime();
  const router = useRouter();

  const filterFields = useMemo<FilterFieldDef[]>(() => {
    const system: FilterFieldDef[] = [
      { field: 'name', label: 'Name', type: 'text' },
      { field: 'phone', label: 'Phone', type: 'text' },
      { field: 'email', label: 'Email', type: 'text' },
      { field: 'language', label: 'Language', type: 'text' },
      { field: 'countryCode', label: 'Country', type: 'text' },
      { field: 'priority', label: 'Priority', type: 'enum', options: PRIORITY_OPTIONS },
      {
        field: 'assignee',
        label: 'Assignee',
        type: 'enum',
        options: [
          { label: 'Unassigned', value: 'unassigned' },
          ...members.map((m) => ({ label: m.name ?? m.email, value: m.userId })),
        ],
      },
      { field: 'channelType', label: 'Channel', type: 'enum', options: channelTypeOptions },
      {
        field: 'lifecycle',
        label: 'Lifecycle',
        type: 'enum',
        options: stages.map((s) => ({ label: s.label, value: s.key })),
      },
      {
        field: 'tags',
        label: 'Tags',
        type: 'enum',
        options: tags.map((t) => ({ label: `${t.emoji ? `${t.emoji} ` : ''}${t.name}`, value: t.id })),
      },
      { field: 'lastMessageAt', label: 'Last message', type: 'date' },
      { field: 'createdAt', label: 'Created', type: 'date' },
    ];
    const custom: FilterFieldDef[] = fields
      .filter((f) => f.visibility === 'always')
      .map((f) => ({
        field: `customFields.${f.key}`,
        label: f.label,
        type: customFieldFilterType(f),
        options: f.type === 'list' ? (f.options ?? []).map((o) => ({ label: o, value: o })) : undefined,
      }));
    return [...system, ...custom];
  }, [members, channelTypeOptions, stages, tags, fields]);

  return useMemo<ResourceListConfig<ContactListItem>>(() => {
    const columns: ColumnDef<ContactListItem>[] = [
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
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => <span className="font-medium text-foreground">{row.original.name}</span>,
        size: 200,
        enableSorting: true,
      },
      {
        id: 'phone',
        accessorFn: (row) => row.phone,
        meta: { headerTitle: 'Phone' },
        header: ({ column }) => <DataGridColumnHeader title="Phone" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{row.original.phone ?? '-'}</span>
        ),
        size: 160,
        enableSorting: true,
      },
      {
        id: 'email',
        accessorFn: (row) => row.email,
        meta: { headerTitle: 'Email' },
        header: ({ column }) => <DataGridColumnHeader title="Email" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{row.original.email ?? '-'}</span>
        ),
        size: 200,
        enableSorting: true,
      },
      {
        id: 'lifecycle',
        accessorFn: (row) => row.lifecycle?.label ?? '',
        meta: { headerTitle: 'Lifecycle' },
        header: ({ column }) => <DataGridColumnHeader title="Lifecycle" column={column} />,
        cell: ({ row }) => <ContactLifecycleCell lifecycle={row.original.lifecycle} />,
        size: 150,
        enableSorting: true,
      },
      {
        id: 'tags',
        accessorFn: (row) => row.tags.map((t) => t.name).join(', '),
        meta: { headerTitle: 'Tags' },
        header: ({ column }) => <DataGridColumnHeader title="Tags" column={column} />,
        cell: ({ row }) => <ContactTagsCell tags={row.original.tags} />,
        size: 220,
        enableSorting: false,
      },
      {
        id: 'assignee',
        accessorFn: (row) => row.assignedUserName ?? '',
        meta: { headerTitle: 'Assignee' },
        header: ({ column }) => <DataGridColumnHeader title="Assignee" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm">{row.original.assignedUserName ?? 'Unassigned'}</span>
        ),
        size: 160,
        enableSorting: true,
      },
      {
        id: 'channel',
        accessorFn: (row) => row.channels.map((c) => c.name).join(', '),
        meta: { headerTitle: 'Channel' },
        header: ({ column }) => <DataGridColumnHeader title="Channel" column={column} />,
        cell: ({ row }) => <ContactChannelsCell channels={row.original.channels} />,
        size: 180,
        enableSorting: false,
      },
      {
        id: 'lastMessageAt',
        accessorFn: (row) => row.lastMessageAt,
        meta: { headerTitle: 'Last message' },
        header: ({ column }) => <DataGridColumnHeader title="Last message" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.lastMessageAt ? formatDateTime(row.original.lastMessageAt) : 'Never'}
          </span>
        ),
        size: 170,
        enableSorting: true,
      },
      {
        id: 'createdAt',
        accessorFn: (row) => row.createdAt,
        meta: { headerTitle: 'Created' },
        header: ({ column }) => <DataGridColumnHeader title="Created" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{formatDate(row.original.createdAt)}</span>
        ),
        size: 140,
        enableSorting: true,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => {
          const meta = table.options.meta;
          const index = (meta?.pageStartIndex ?? 0) + row.index;
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu
                actions={actions}
                rows={[row.original]}
                runtime={{ ctx: meta?.resourceCtx, index, reload: meta?.reload ?? (() => {}) }}
                surface="row"
              />
            </div>
          );
        },
        size: 60,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
    ];

    return {
      viewKey: 'omnichannel.contacts.list',
      columns,
      getRowId: (c) => c.id,
      rowHref: (c) => contactFormPath(c.id),
      fetcher: (q) => contactService.list(workspaceId, q),
      exporter: async (q, cols, ids) => {
        try {
          return await contactService.exportContacts(workspaceId, {
            columns: cols,
            ids,
            search: q.search,
            filter: q.filter,
            segment: q.segment,
            sortBy: q.sort?.id,
            sortDir: q.sort?.desc ? 'desc' : 'asc',
          });
        } catch (error) {
          if (error instanceof ExportPendingError) exportPendingToast(router.push);
          throw error;
        }
      },
      filterFields,
      exportColumns: [
        { id: 'id', label: 'ID' },
        { id: 'name', label: 'Name' },
        { id: 'phone', label: 'Phone' },
        { id: 'email', label: 'Email' },
        { id: 'lifecycle', label: 'Lifecycle' },
        { id: 'tags', label: 'Tags' },
        { id: 'assignee', label: 'Assignee' },
        { id: 'channel', label: 'Channel' },
        { id: 'lastMessageAt', label: 'Last message' },
        { id: 'createdAt', label: 'Created' },
      ],
      actions,
      searchPlaceholder: 'Search contacts…',
      searchHints: ['Name', 'Phone', 'Email'],
      defaultSort: { id: 'lastMessageAt', desc: true },
      enableStatusViews: false,
      segments: segmentOptions(segments),
      onFilterChange,
      exportFilename: 'contacts',
      createLabel: 'Add contact',
      createPermission: 'contacts.manage',
      onCreate: () => router.push(contactNewPath),
      importer: { entityType: 'omnichannel_contacts', writePermission: 'contacts.import', context: { workspaceId } },
    };
  }, [workspaceId, filterFields, actions, segments, onFilterChange, formatDate, formatDateTime, router]);
}
