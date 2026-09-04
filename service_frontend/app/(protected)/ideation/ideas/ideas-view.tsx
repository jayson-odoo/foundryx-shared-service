'use client';

import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { ResourceList } from '@/components/platform/resource-list';
import { useIdeas } from '@/hooks/use-ideas';
import type { IdeaCreateInput } from '@/services/ideation-service';
import { IDEA_NEXT_STATUS, type Idea } from '@/types/ideation';
import { useIdeasListConfig } from './use-ideas-list-config';
import { IdeaClusterSuggestions } from './cluster-suggestions';
import { IdeaCaptureDialog } from './idea-capture-dialog';
import { promoteIdeasToBr } from './promote-to-br';

/**
 * The Ideas repository grid - the SINGLE list/grid component used by BOTH the
 * operator page and the chrome-less host iframe (WS-C1 / AC-CAP-9/10). The
 * backend + URLs it talks to come from `useIdeationRuntime()` (operator default
 * or embed), so the component code is mode-agnostic: shared ResourceList with
 * opt-in row drag-reorder (row order = priority), per-user vote toggle, and the
 * capture dialog for create.
 */
export function IdeasView() {
  const router = useRouter();
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
      onPromote: (selected: Idea[]) => promoteIdeasToBr(selected, router),
    }),
    [vote, setStatus, remove, reorderPriority, router],
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
      <IdeaClusterSuggestions
        onPromote={(cluster, meta) => promoteIdeasToBr(cluster, router, meta)}
      />
      <ResourceList key={version} config={config} hideHeader restoreFromCtx />
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
