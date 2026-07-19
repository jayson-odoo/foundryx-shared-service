'use client';

import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { useIdeas } from '@/hooks/use-ideas';
import type { IdeaCreateInput } from '@/services/ideation-service';
import { IDEA_NEXT_STATUS, type Idea } from '@/types/ideation';
import { useIdeasListConfig } from './use-ideas-list-config';
import { IdeaCaptureDialog } from './idea-capture-dialog';

/**
 * Idea repository (plan Phase A) on the shared ResourceList (same component as
 * the Users list) with opt-in row drag-reorder — row order IS priority. Votes
 * are a per-user toggle; row-click opens the idea form. Phase 1 = mock service.
 *
 * TODO(Phase 2): RequirePermission "ideas.view" once permissions are seeded.
 */
function IdeasView() {
  const { ideas, products, loading, error, create, vote, setStatus, reorderPriority, remove } =
    useIdeas();
  const [dialogOpen, setDialogOpen] = useState(false);

  // Remount the ResourceList whenever the ideas change (mutation) so its
  // client-side fetcher re-pages over fresh data (quick-replies pattern).
  const [version, setVersion] = useState(0);
  const prev = useRef(ideas);
  useEffect(() => {
    if (prev.current !== ideas) {
      prev.current = ideas;
      setVersion((v) => v + 1);
    }
  }, [ideas]);

  const handlers = useMemo(
    () => ({
      onCreate: () => setDialogOpen(true),
      onVote: async (idea: Idea, dir: 'up' | 'down') => {
        try {
          await vote(idea.id, dir);
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Could not vote.');
        }
      },
      onAdvance: async (idea: Idea) => {
        const next = IDEA_NEXT_STATUS[idea.status];
        if (!next) return;
        try {
          await setStatus(idea.id, next);
          toast.success(`Moved to ${next}.`);
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Could not advance the idea.');
        }
      },
      onArchive: async (idea: Idea) => {
        try {
          await setStatus(idea.id, 'archived');
          toast.success('Idea archived.');
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Could not archive the idea.');
        }
      },
      onRestore: async (idea: Idea) => {
        try {
          await setStatus(idea.id, 'captured');
          toast.success('Idea restored.');
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Could not restore the idea.');
        }
      },
      onDelete: async (idea: Idea) => {
        try {
          await remove(idea.id);
          toast.success('Idea deleted.');
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Could not delete the idea.');
        }
      },
      onReorder: async (orderedIds: string[]) => {
        try {
          await reorderPriority(orderedIds);
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Could not reorder.');
        }
      },
    }),
    [vote, setStatus, remove, reorderPriority],
  );

  const config = useIdeasListConfig(ideas, handlers);

  const handleCreate = async (input: IdeaCreateInput) => {
    await create(input);
    toast.success('Idea captured.');
  };

  if (error && ideas.length === 0) {
    return <p className="text-sm text-destructive">{error}</p>;
  }
  if (loading && ideas.length === 0) {
    return <p className="text-sm text-muted-foreground">Loading ideas…</p>;
  }

  return (
    <Fragment>
      <ResourceList key={version} config={config} />
      {dialogOpen && (
        <IdeaCaptureDialog
          products={products}
          onClose={() => setDialogOpen(false)}
          onCreate={handleCreate}
        />
      )}
    </Fragment>
  );
}

export default function IdeasPage() {
  return (
    <Fragment>
      <Container width="fluid">
        <Toolbar>
          <ToolbarHeading>
            <ToolbarPageTitle />
            <ToolbarDescription>
              The raw idea repository — drag the grip to reprioritise (top = highest).
            </ToolbarDescription>
          </ToolbarHeading>
        </Toolbar>
      </Container>
      <Container width="fluid">
        <IdeasView />
      </Container>
    </Fragment>
  );
}
