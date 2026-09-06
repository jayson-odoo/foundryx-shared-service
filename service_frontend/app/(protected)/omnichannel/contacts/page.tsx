'use client';

/**
 * Contacts list host (plan 26, D-A2-1/D-A2-10) - the Contacts module's
 * Resource-shell list. Workspace resolves exactly like the Inbox (default
 * workspace first); a workspace picker renders in the header only when the
 * tenant has more than one workspace (the segment control already occupies
 * the list toolbar).
 */
import { Fragment, useCallback, useEffect, useState } from 'react';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { RequirePermission } from '@/components/common/require-permission';
import { PageHeader } from '@/components/platform/page-header';
import { ResourceList } from '@/components/platform/resource-list';
import { SearchSelect } from '@/components/platform/search-select';
import { useCan } from '@/hooks/use-can';
import { useActiveWorkspace } from '@/hooks/use-contacts';
import { useContactSegments } from '@/hooks/use-contact-segments';
import { useContactTags } from '@/hooks/use-contact-tags';
import { useContactFields } from '@/hooks/use-contact-fields';
import { useContactLifecycleStages } from '@/hooks/use-contact-lifecycle-stages';
import { useWorkspaceMembers } from '@/hooks/use-workspace-members';
import { useContactBulk, reportBulkResult } from '@/hooks/use-contact-bulk';
import { channelService } from '@/services/channel-service';
import type { ContactListItem } from '@/types/omnichannel';
import type { FilterGroup } from '@/types/resource';
import { BulkAssignDialog } from './components/bulk-assign-dialog';
import { BulkLifecycleDialog } from './components/bulk-lifecycle-dialog';
import { BulkTagsDialog } from './components/bulk-tags-dialog';
import { ManageSegmentsDialog } from './components/manage-segments-dialog';
import { SaveSegmentDialog } from './components/save-segment-dialog';
import { useContactActions } from './components/use-contact-actions';
import { useContactsListConfig } from './components/use-contacts-list-config';
import { useSegmentDeleteController } from './components/use-segment-delete-controller';

interface PendingAction {
  rows: ContactListItem[];
  reload: () => void;
}

/** Finding 10 (review round 1): a bulk failure reason names the record by
 * its display NAME, never a bare UUID - the dialog already holds the
 * selected rows. */
function nameForId(rows: ContactListItem[]): (id: string) => string {
  const byId = new Map(rows.map((r) => [r.id, r.name]));
  return (id) => byId.get(id) ?? id;
}

export default function ContactsPage() {
  const { can } = useCan();
  const { workspaceId, workspaces, ready, setWorkspaceId } = useActiveWorkspace();
  const {
    segments,
    create: createSegment,
    update: updateSegment,
    refresh: refreshSegments,
  } = useContactSegments(workspaceId);
  const { tags } = useContactTags(workspaceId);
  const { fields } = useContactFields(workspaceId);
  const { stages } = useContactLifecycleStages(workspaceId);
  const { members } = useWorkspaceMembers(workspaceId);
  const bulk = useContactBulk(workspaceId);
  // Review round 2, should-fix 4: owned HERE (not inside the dialog) so the
  // countdown/poll/refresh survives "Manage segments" closing mid-window.
  const segmentDelete = useSegmentDeleteController(() => void refreshSegments());

  const [channelTypeOptions, setChannelTypeOptions] = useState<{ label: string; value: string }[]>([]);
  useEffect(() => {
    if (!workspaceId) return;
    channelService
      .listByWorkspace(workspaceId)
      .then((channels) => {
        const seen = new Set<string>();
        for (const c of channels) seen.add(c.channelType);
        setChannelTypeOptions(Array.from(seen).map((v) => ({ label: v, value: v })));
      })
      .catch(() => setChannelTypeOptions([]));
  }, [workspaceId]);

  const [currentFilter, setCurrentFilter] = useState<FilterGroup | null>(null);

  const [assignPending, setAssignPending] = useState<PendingAction | null>(null);
  const [tagsPending, setTagsPending] = useState<(PendingAction & { mode: 'add' | 'remove' }) | null>(null);
  const [lifecyclePending, setLifecyclePending] = useState<PendingAction | null>(null);
  const [saveSegmentOpen, setSaveSegmentOpen] = useState(false);
  const [manageSegmentsOpen, setManageSegmentsOpen] = useState(false);

  // Finding 7 (review round 1): stable callback identities - a fresh object
  // literal (with fresh arrow functions) on every render used to recompute
  // `actions` -> `config`/`config.fetcher` downstream, and
  // `useResourceList`'s fetch effect keys off `fetcher` identity, so the
  // list refetched on every render instead of only on an actual query
  // change. `setState` setters are already stable, so these need no deps.
  const onBulkAssign = useCallback(
    (rows: ContactListItem[], reload: () => void) => setAssignPending({ rows, reload }),
    [],
  );
  const onAddTags = useCallback(
    (rows: ContactListItem[], reload: () => void) => setTagsPending({ rows, reload, mode: 'add' }),
    [],
  );
  const onRemoveTags = useCallback(
    (rows: ContactListItem[], reload: () => void) => setTagsPending({ rows, reload, mode: 'remove' }),
    [],
  );
  const onMoveLifecycle = useCallback(
    (rows: ContactListItem[], reload: () => void) => setLifecyclePending({ rows, reload }),
    [],
  );
  const actions = useContactActions({ onBulkAssign, onAddTags, onRemoveTags, onMoveLifecycle });

  const config = useContactsListConfig({
    workspaceId: workspaceId ?? '',
    segments,
    tags,
    fields,
    stages,
    members,
    channelTypeOptions,
    actions,
    onFilterChange: setCurrentFilter,
  });

  const canManageSegments = can('segments.manage');

  if (!ready) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  return (
    <RequirePermission permission="contacts.read">
      <Fragment>
        <Container width="fluid">
          <PageHeader
            description="Every contact in this workspace - lifecycle, tags, assignee and channel."
            actions={
              <Fragment>
                {workspaces.length > 1 && (
                  <SearchSelect
                    ariaLabel="Workspace"
                    className="w-56"
                    value={workspaceId}
                    onChange={setWorkspaceId}
                    options={workspaces.map((w) => ({ label: w.name, value: w.id }))}
                  />
                )}
                {canManageSegments && currentFilter && (
                  <Button variant="outline" size="sm" onClick={() => setSaveSegmentOpen(true)}>
                    Save as segment
                  </Button>
                )}
                {canManageSegments && segments.length > 0 && (
                  <Button variant="outline" size="sm" onClick={() => setManageSegmentsOpen(true)}>
                    Manage segments
                  </Button>
                )}
              </Fragment>
            }
          />
        </Container>
        <Container width="fluid">
          {workspaceId ? <ResourceList config={config} hideHeader restoreFromCtx /> : null}
        </Container>

        {currentFilter && (
          <SaveSegmentDialog
            open={saveSegmentOpen}
            onOpenChange={setSaveSegmentOpen}
            filter={currentFilter}
            onSave={(values) =>
              createSegment({ name: values.name, description: values.description, filter: currentFilter })
            }
          />
        )}

        <ManageSegmentsDialog
          open={manageSegmentsOpen}
          onOpenChange={setManageSegmentsOpen}
          segments={segments}
          filterFields={config.filterFields}
          onRename={(id, name) => updateSegment(id, { name })}
          onEditFilter={(id, filter) => (filter ? updateSegment(id, { filter }) : Promise.resolve())}
          deletingId={segmentDelete.deletingId}
          onDelete={segmentDelete.startDelete}
        />

        <BulkAssignDialog
          open={!!assignPending}
          onOpenChange={(v) => !v && setAssignPending(null)}
          members={members}
          count={assignPending?.rows.length ?? 0}
          onConfirm={async (assigneeUserId) => {
            if (!assignPending) return;
            const result = await bulk.assign(assignPending.rows.map((r) => r.id), assigneeUserId);
            reportBulkResult(result, 'assigned', nameForId(assignPending.rows));
            assignPending.reload();
          }}
        />

        <BulkTagsDialog
          open={!!tagsPending}
          onOpenChange={(v) => !v && setTagsPending(null)}
          mode={tagsPending?.mode ?? 'add'}
          tags={tags}
          count={tagsPending?.rows.length ?? 0}
          onConfirm={async (mode, tagIds) => {
            if (!tagsPending) return;
            const result = await bulk.tags(tagsPending.rows.map((r) => r.id), mode, tagIds);
            reportBulkResult(result, mode === 'add' ? 'tagged' : 'untagged', nameForId(tagsPending.rows));
            tagsPending.reload();
          }}
        />

        <BulkLifecycleDialog
          open={!!lifecyclePending}
          onOpenChange={(v) => !v && setLifecyclePending(null)}
          stages={stages}
          count={lifecyclePending?.rows.length ?? 0}
          onConfirm={async (toStatusId) => {
            if (!lifecyclePending) return;
            const result = await bulk.lifecycle(lifecyclePending.rows.map((r) => r.id), toStatusId);
            reportBulkResult(result, 'moved', nameForId(lifecyclePending.rows));
            lifecyclePending.reload();
          }}
        />
      </Fragment>
    </RequirePermission>
  );
}
