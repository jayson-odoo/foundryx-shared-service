'use client';

import { useEffect, useMemo, useState } from 'react';
import { LoaderCircleIcon, Plus, X } from 'lucide-react';
import { toast } from '@/lib/toast';
import type { ColumnDef } from '@tanstack/react-table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { ClampedText } from '@/components/platform/clamped-text';
import { MultiSelect } from '@/components/platform/multi-select';
import {
  ResourceList,
  type ResourceAction,
  type ResourceListConfig,
} from '@/components/platform/resource-list';
import { toCsv } from '@/lib/csv';
import { useCan } from '@/hooks/use-can';
import { useBrIdeas } from '@/hooks/use-br-ideas';
import { businessRequirementService } from '@/services/business-requirement-service';
import { ideationService } from '@/services/ideation-service';
import { ideaFormHref } from '@/app/(protected)/ideation/ideas/components/paths';
import type { ListQuery, ListResult } from '@/types/resource';
import type { Idea } from '@/types/ideation';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export interface BrIdeasTabProps {
  brId: string;
  /** The BR's product - a BR only links same-product ideas (AC-BI-17). */
  productId: string;
  reloadToken: number;
  /** Bumped after a link/unlink so the grill re-seeds from fresh source ideas
   * next turn (AC-BI-33) and the linked list reloads. */
  onChanged: () => void;
}

/** Ideas tab - the linked ideas feeding this BR (lineage, AC-BI-35) on the shared
 * ResourceList (NOT a hand-rolled list, AC-BI-29c). Each row navigates to the
 * idea detail. Link (the "Link ideas from this product" picker) + unlink (a row/
 * bulk action) are preserved and gated by `.manage`; linking an idea mid-session
 * re-seeds the grill's source context next turn (AC-BI-33). Data via `useBrIdeas`
 * (UI → hook → service). */
/** Grace-window action key encodes the composite (brId, ideaId) link row -
 * the deferred-actions registry's `entity_id` is a bare string column and
 * this link has no id of its own the frontend row type carries (fix round
 * 1, T5, item 15). */
const getUnlinkEntityId = (brId: string) => (row: Idea) => `${brId}:${row.id}`;

export function BrIdeasTab({ brId, productId, reloadToken, onChanged }: BrIdeasTabProps) {
  const { ideas } = useBrIdeas(brId, reloadToken);
  const { can } = useCan();
  const canManage = can('ideation.business_requirements.manage');
  const unlinkEntityId = useMemo(() => getUnlinkEntityId(brId), [brId]);

  const config = useMemo<ResourceListConfig<Idea>>(() => {
    const rows = ideas ?? [];

    const actions: ResourceAction<Idea>[] = canManage
      ? [
          {
            id: 'unlink',
            label: 'Unlink',
            icon: X,
            tone: 'destructive',
            surfaces: { row: true, bulk: true },
            // Grace-window deferred action (sprint-4/23, T5 fix round 1,
            // item 15) - no confirm, no `run` (the registered
            // `ideation_business_requirements.unlink_idea` handler commits
            // it server-side).
            deferred: {
              actionKey: 'ideation_business_requirements.unlink_idea',
              entityType: 'ideation_br_idea_link',
            },
          },
        ]
      : [];

    const columns: ColumnDef<Idea>[] = [
      {
        id: 'problem',
        header: () => 'Idea',
        cell: ({ row }) => <ClampedText text={row.original.problem} lines={2} />,
        size: 360,
        enableSorting: false,
      },
      {
        id: 'submitter',
        header: () => 'Submitter',
        cell: ({ row }) => (
          <span className="text-muted-foreground">{row.original.submitterName}</span>
        ),
        size: 150,
        enableSorting: false,
      },
      {
        id: 'product',
        header: () => 'Product',
        cell: ({ row }) => <Badge variant="secondary">{row.original.productName}</Badge>,
        size: 150,
        enableSorting: false,
      },
    ];

    if (canManage) {
      columns.push({
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
              getEntityId={unlinkEntityId}
              onDeferredCommitted={onChanged}
            />
          </div>
        ),
        size: 56,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      });
    }

    const fetcher = async (query: ListQuery): Promise<ListResult<Idea>> => {
      let data = rows;
      if (query.search) {
        const s = query.search.toLowerCase();
        data = data.filter(
          (r) =>
            r.problem.toLowerCase().includes(s) ||
            r.submitterName.toLowerCase().includes(s) ||
            r.productName.toLowerCase().includes(s),
        );
      }
      const total = data.length;
      const start = query.page * query.pageSize;
      return { data: data.slice(start, start + query.pageSize), total, page: query.page };
    };

    const exporter = async (query: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...query, page: 0, pageSize: 10_000 });
      return toCsv(
        ['Idea', 'Submitter', 'Product'],
        data.map((r) => [r.problem, r.submitterName, r.productName]),
      );
    };

    return {
      viewKey: 'ideation.br.ideas',
      getRowId: (row) => row.id,
      rowHref: (row) => ideaFormHref(row.id),
      fetcher,
      exporter,
      searchPlaceholder: 'Search linked ideas…',
      searchHints: ['Idea', 'Submitter'],
      // Lineage list - no Active/Trashed segmentation (there is no trashed view).
      enableStatusViews: false,
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'problem', label: 'Idea' },
        { id: 'submitter', label: 'Submitter' },
      ],
      actions,
      getEntityId: unlinkEntityId,
    };
  }, [ideas, canManage, unlinkEntityId, onChanged]);

  return (
    <Card>
      <CardContent className="space-y-4 py-4">
        {canManage && (
          <LinkIdeas
            brId={brId}
            productId={productId}
            linked={ideas ?? []}
            onLinked={onChanged}
          />
        )}

        {ideas === null ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            <LoaderCircleIcon className="size-5 animate-spin" />
          </div>
        ) : ideas.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">No linked ideas.</p>
        ) : (
          // Remount on reload so the freshly-fetched linked set drives the list.
          <ResourceList key={reloadToken} config={config} hideHeader />
        )}
      </CardContent>
    </Card>
  );
}

function LinkIdeas({
  brId,
  productId,
  linked,
  onLinked,
}: {
  brId: string;
  productId: string;
  linked: Idea[];
  onLinked: () => void;
}) {
  const [candidates, setCandidates] = useState<Idea[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    ideationService
      .listIdeas()
      .then((all) => !cancelled && setCandidates(all))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [linked]);

  const linkedIds = useMemo(() => new Set(linked.map((i) => i.id)), [linked]);
  const options = useMemo(
    () =>
      candidates
        .filter((i) => i.productId === productId && !linkedIds.has(i.id))
        .map((i) => ({ value: i.id, label: i.problem })),
    [candidates, productId, linkedIds],
  );

  const link = async () => {
    if (selected.length === 0) return;
    setBusy(true);
    try {
      await businessRequirementService.linkIdeas(brId, selected);
      toast.success(selected.length === 1 ? 'Idea linked.' : `${selected.length} ideas linked.`);
      setSelected([]);
      onLinked();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not link ideas.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <MultiSelect
          options={options}
          value={selected}
          onChange={setSelected}
          placeholder="Link ideas from this product…"
        />
      </div>
      <Button onClick={link} disabled={busy || selected.length === 0} className="shrink-0">
        <Plus className="size-4" />
        Link
      </Button>
    </div>
  );
}
