'use client';

import { useMemo } from 'react';
import { usePathname } from 'next/navigation';
import { toast } from 'sonner';
import type { ColumnDef } from '@tanstack/react-table';
import { ArrowRight, UserCog, Send } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import type { StatusNodeData, StatusTransition } from '@/types/status-engine';
import type { TemplateChild } from '@/types/ems';
import { emsService } from '@/services/ems-service';
import { toCsv } from '@/lib/csv';

const stop = (e: React.MouseEvent) => e.stopPropagation();

/** One available eligibility move for a participant (graph outgoing edge). */
export interface ParticipantMove {
  toStatusId: string;
  label: string;
}

/** A participant joined with profile + role/segment/status display fields. */
export interface ParticipantRow {
  id: string;
  profileId: string;
  profileName: string;
  profileEmail: string;
  roleName: string;
  segmentName: string;
  statusId: string | null;
  statusLabel: string;
  moves: ParticipantMove[];
}

export interface ParticipantsConfigCtx {
  projectId: string;
  statuses: StatusNodeData[];
  transitions: StatusTransition[];
  roles: TemplateChild[];
  segments: TemplateChild[];
  onAdd: () => void;
  onAssign: (row: ParticipantRow) => void;
  onNominate: (row: ParticipantRow) => void;
}

/** Embedded participants list for an event — resolves profile, role, segment,
 * and the scoped eligibility status; row actions assign role/segment and move
 * the participant through the eligibility graph (AC-11-01/13). */
export function useParticipantsListConfig(ctx: ParticipantsConfigCtx): ResourceListConfig<ParticipantRow> {
  const pathname = usePathname();
  const { projectId, statuses, transitions, roles, segments, onAdd, onAssign, onNominate } = ctx;

  return useMemo<ResourceListConfig<ParticipantRow>>(() => {
    const statusLabel = new Map(statuses.map((s) => [s.id, s.label]));
    const roleName = new Map(roles.map((r) => [r.id, r.name]));
    const segmentName = new Map(segments.map((s) => [s.id, s.name]));

    // Per-row "…" menu: ONE item per available next state (the graph already
    // knows where the participant can go) that fires the move directly, plus
    // Assign role/segment. Built per row because the move targets are
    // row-specific (depend on the participant's current status).
    const rowActions = (row: ParticipantRow, reload: () => void): ResourceAction<ParticipantRow>[] => [
      ...row.moves.map((m) => ({
        id: `move-${m.toStatusId}`,
        label: `${m.label}`,
        icon: ArrowRight,
        surfaces: { row: true, form: false, bulk: false },
        permission: 'participants.manage',
        run: async () => {
          try {
            await emsService.transitionParticipant(projectId, row.id, m.toStatusId);
            reload();
          } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not move the participant.');
          }
        },
      })),
      {
        id: 'assign',
        label: 'Assign role / segment',
        icon: UserCog,
        surfaces: { row: true, form: false, bulk: false },
        permission: 'participants.manage',
        run: () => onAssign(row),
      },
      {
        id: 'nominate',
        label: 'Nominate / transfer ticket',
        icon: Send,
        surfaces: { row: true, form: false, bulk: false },
        permission: 'tickets.manage',
        run: () => onNominate(row),
      },
    ];

    const columns: ColumnDef<ParticipantRow>[] = [
      {
        id: 'profile',
        accessorFn: (r) => r.profileName,
        meta: { headerTitle: 'Profile' },
        header: ({ column }) => <DataGridColumnHeader title="Profile" column={column} />,
        cell: ({ row }) => (
          <div className="flex flex-col">
            <span className="font-medium leading-tight text-foreground">{row.original.profileName}</span>
            <span className="text-xs text-muted-foreground">{row.original.profileEmail}</span>
          </div>
        ),
        size: 260,
        enableSorting: true,
      },
      {
        id: 'role',
        accessorFn: (r) => r.roleName,
        meta: { headerTitle: 'Role' },
        header: ({ column }) => <DataGridColumnHeader title="Role" column={column} />,
        cell: ({ row }) =>
          row.original.roleName ? (
            <Badge variant="secondary" appearance="light" size="sm">{row.original.roleName}</Badge>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
        size: 150,
        enableSorting: false,
      },
      {
        id: 'segment',
        accessorFn: (r) => r.segmentName,
        meta: { headerTitle: 'Segment' },
        header: ({ column }) => <DataGridColumnHeader title="Segment" column={column} />,
        cell: ({ row }) =>
          row.original.segmentName ? (
            <Badge variant="secondary" appearance="light" size="sm">{row.original.segmentName}</Badge>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
        size: 150,
        enableSorting: false,
      },
      {
        id: 'status',
        accessorFn: (r) => r.statusLabel,
        meta: { headerTitle: 'Eligibility' },
        header: ({ column }) => <DataGridColumnHeader title="Eligibility" column={column} />,
        cell: ({ row }) =>
          row.original.statusLabel ? (
            <Badge variant="primary" appearance="light" size="sm">{row.original.statusLabel}</Badge>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
        size: 150,
        enableSorting: false,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => {
          const reload = table.options.meta?.reload ?? (() => {});
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu
                actions={rowActions(row.original, reload)}
                rows={[row.original]}
                runtime={{ reload }}
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

    const fetcher = async (q: ListQuery): Promise<ListResult<ParticipantRow>> => {
      const [participants, profiles] = await Promise.all([
        emsService.listParticipants(projectId, { pageSize: 200 }),
        emsService.listProfiles({ pageSize: 200 }),
      ]);
      const byId = new Map(profiles.items.map((p) => [p.id, p]));
      let rows: ParticipantRow[] = participants.items.map((pp) => {
        const prof = byId.get(pp.profileId);
        const moves = pp.statusId
          ? transitions
              .filter((t) => t.fromStatusId === pp.statusId)
              .map((t) => ({ toStatusId: t.toStatusId, label: statusLabel.get(t.toStatusId) || t.label }))
          : [];
        return {
          id: pp.id,
          profileId: pp.profileId,
          profileName: prof?.fullName || prof?.email || pp.profileId,
          profileEmail: prof?.email ?? '',
          roleName: (pp.roleId && roleName.get(pp.roleId)) || '',
          segmentName: (pp.segmentId && segmentName.get(pp.segmentId)) || '',
          statusId: pp.statusId,
          statusLabel: (pp.statusId && statusLabel.get(pp.statusId)) || '',
          moves,
        };
      });
      if (q.search) {
        const s = q.search.toLowerCase();
        rows = rows.filter(
          (r) => r.profileName.toLowerCase().includes(s) || r.profileEmail.toLowerCase().includes(s),
        );
      }
      if (q.sort) {
        rows = [...rows].sort((a, b) => a.profileName.localeCompare(b.profileName));
        if (q.sort.desc) rows.reverse();
      }
      const total = rows.length;
      const start = q.page * q.pageSize;
      return { data: rows.slice(start, start + q.pageSize), total, page: q.page };
    };

    const exporter = async (q: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...q, page: 0, pageSize: 10_000 });
      return toCsv(
        ['Profile', 'Email', 'Role', 'Segment', 'Eligibility'],
        data.map((r) => [r.profileName, r.profileEmail, r.roleName, r.segmentName, r.statusLabel]),
      );
    };

    return {
      viewKey: 'ems.participants',
      getRowId: (r) => r.id,
      rowHref: () => pathname,
      fetcher,
      exporter,
      searchPlaceholder: 'Search participants…',
      searchHints: ['Profile', 'Email'],
      defaultSort: { id: 'profile', desc: false },
      exportFilename: 'participants',
      enableStatusViews: false,
      createLabel: 'Add participant',
      createPermission: 'participants.manage',
      onCreate: onAdd,
      importer: {
        entityType: 'project_participant',
        writePermission: 'participants.manage',
        context: { project_id: projectId },
      },
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'profile', label: 'Profile' },
        { id: 'role', label: 'Role' },
        { id: 'segment', label: 'Segment' },
        { id: 'status', label: 'Eligibility' },
      ],
      actions: [],
    };
  }, [pathname, projectId, statuses, transitions, roles, segments, onAdd, onAssign, onNominate]);
}
