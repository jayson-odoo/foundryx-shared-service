'use client';

import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { ResourceList } from '@/components/platform/resource-list';
import { useIdeas } from '@/hooks/use-ideas';
import type { IdeaCreateInput } from '@/services/ideation-service';
import { businessRequirementService } from '@/services/business-requirement-service';
import { brFormHref } from '@/app/(protected)/ideation/business-requirements/components/paths';
import { IDEA_NEXT_STATUS, type Idea } from '@/types/ideation';
import { useIdeasListConfig } from './use-ideas-list-config';
import { IdeaClusterSuggestions } from './cluster-suggestions';
import { IdeaCaptureDialog } from './idea-capture-dialog';

/**
 * The Ideas repository grid — the SINGLE list/grid component used by BOTH the
 * operator page and the chrome-less host iframe (WS-C1 / AC-CAP-9/10). The
 * backend + URLs it talks to come from `useIdeationRuntime()` (operator default
 * or embed), so the component code is mode-agnostic: shared ResourceList with
 * opt-in row drag-reorder (row order = priority), per-user vote toggle, and the
 * capture dialog for create.
 */
/** Create a draft BR from a set of ideas and land on its Grill tab (AC-BI-32).
 * All ideas must share ONE product (a BR links same-product ideas, AC-BI-17). */
async function promoteIdeasToBr(
  ideas: Idea[],
  router: ReturnType<typeof useRouter>,
): Promise<void> {
  if (ideas.length === 0) return;
  const productIds = new Set(ideas.map((i) => i.productId));
  if (productIds.size > 1) {
    toast.error('Select ideas from a single product to promote them together.');
    return;
  }
  try {
    const created = await businessRequirementService.create({
      productId: ideas[0].productId,
      ideaIds: ideas.map((i) => i.id),
    });
    toast.success('Draft requirement created — start grilling.');
    router.push(brFormHref(created.id, { tab: 'grill' }));
  } catch (e) {
    toast.error(e instanceof Error ? e.message : 'Could not promote to a business requirement.');
  }
}

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
        onPromote={(cluster) => promoteIdeasToBr(cluster, router)}
      />
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
