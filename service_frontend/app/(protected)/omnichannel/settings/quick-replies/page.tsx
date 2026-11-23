'use client';

import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from '@/lib/toast';
import type { QuickReply } from '@/types/omnichannel';
import { useQuickReplies } from '@/hooks/use-quick-replies';
import type {
  QuickReplyCreateInput,
  QuickReplyUpdateInput,
} from '@/services/quick-reply-service';
import { workspaceService } from '@/services/workspace-service';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { QuickReplyDialog } from './quick-reply-dialog';
import { useQuickRepliesListConfig } from './use-quick-replies-list-config';
import { useFx } from '@/hooks/use-fx';
import { useFxUserName } from '../workspaces/components/use-fx-user-name';
import { fxQuickReplyName } from './quick-reply-fx';

/**
 * Quick-replies settings (plan sprint-3/12) - canned responses the inbox
 * composer's ★ picker consumes, on the config-driven Resource shell. Gated by
 * `workspaces.manage`. Workspace resolution mirrors the inbox host: the default
 * workspace, overridable with `?workspaceId=` (same contract as the media page).
 */
function QuickRepliesView() {
  // Resolve the workspace: ?workspaceId= override, else the default workspace.
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [resolving, setResolving] = useState(true);
  useEffect(() => {
    const override = new URLSearchParams(window.location.search).get(
      'workspaceId',
    );
    if (override) {
      setWorkspaceId(override);
      setResolving(false);
      return;
    }
    let active = true;
    workspaceService
      .list({ page: 0, pageSize: 50 })
      .then((res) => {
        if (!active) return;
        const ws = res.data.find((w) => w.isDefault) ?? res.data[0];
        setWorkspaceId(ws?.id ?? null);
      })
      .catch(() => active && setWorkspaceId(null))
      .finally(() => active && setResolving(false));
    return () => {
      active = false;
    };
  }, []);

  const { items, error, create, update, remove } = useQuickReplies(workspaceId);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<QuickReply | null>(null);

  // Remount the ResourceList whenever the underlying items change (initial load
  // + after each mutation) so the client-side fetcher re-pages over fresh data.
  const [version, setVersion] = useState(0);
  const prevItems = useRef(items);
  useEffect(() => {
    if (prevItems.current !== items) {
      prevItems.current = items;
      setVersion((v) => v + 1);
    }
  }, [items]);

  const handlers = useMemo(
    () => ({
      onCreate: () => {
        setEditing(null);
        setDialogOpen(true);
      },
      onEdit: (item: QuickReply) => {
        setEditing(item);
        setDialogOpen(true);
      },
      onDelete: async (item: QuickReply) => {
        try {
          await remove(item.id);
          toast.success('Quick reply deleted.');
        } catch (e) {
          toast.error(
            e instanceof Error
              ? e.message
              : 'Could not delete the quick reply.',
          );
        }
      },
    }),
    [remove],
  );

  const config = useQuickRepliesListConfig(items, handlers);
  const fx = useFx();
  const byWhom = useFxUserName();

  const handleCreate = async (input: QuickReplyCreateInput) => {
    const created = await create(input);
    if (!fx) {
      toast.success('Quick reply created.');
      return;
    }
    // Undo removes the reply just created (the same delete the API offers).
    toast.fxDone({
      what: `Quick reply ${fxQuickReplyName(created)} created`,
      byWhom,
      undo: () => void remove(created.id).catch(() => toast.error("Couldn't undo. The quick reply is still there.")),
    });
  };
  const handleUpdate = async (id: string, input: QuickReplyUpdateInput) => {
    const before = items.find((i) => i.id === id);
    const updated = await update(id, input);
    if (!fx) {
      toast.success('Quick reply saved.');
      return;
    }
    // Undo writes the reply back as it was.
    toast.fxDone({
      what: `Quick reply ${fxQuickReplyName(updated)} saved`,
      byWhom,
      undo: before
        ? () =>
            void update(id, { shortcut: before.shortcut, body: before.body }).catch(() =>
              toast.error("Couldn't undo. The quick reply keeps its new words."),
            )
        : undefined,
    });
  };

  if (!resolving && !workspaceId) {
    return (
      <p className="text-sm text-muted-foreground">
        No workspace is available. Create a workspace first.
      </p>
    );
  }
  if (error && items.length === 0) {
    return <p className="text-sm text-destructive">{error}</p>;
  }

  return (
    <Fragment>
      <ResourceList key={version} config={config} />
      {dialogOpen && (
        <QuickReplyDialog
          item={editing}
          onClose={() => setDialogOpen(false)}
          onCreate={handleCreate}
          onUpdate={handleUpdate}
        />
      )}
    </Fragment>
  );
}

export default function QuickRepliesPage() {
  return (
    <RequirePermission permission="workspaces.manage">
      <Fragment>
        <Container width="fluid">
          <QuickRepliesView />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
