'use client';

import { useCallback, useEffect, useState } from 'react';
import { type IdeaCreateInput } from '@/services/ideation-service';
import { useIdeationRuntime } from '@/hooks/use-ideation-runtime';
import type { BoardColumn, Idea, Product } from '@/types/ideation';

export interface UseIdeas {
  ideas: Idea[];
  products: Product[];
  loading: boolean;
  error: string | null;
  /** Triage-board columns (issue #94, ideation round 2, AC-94-58) - `undefined`
   * on a service that doesn't implement `getBoard` (an older test double); the
   * board falls back to deriving columns from `ideas` itself in that case. */
  columns?: BoardColumn[];
  /** Whether console/`--say` test ideas (issue #1179) are included - off by
   * default; the Ideas list exposes a toggle that flips this + reloads. */
  includeTest: boolean;
  setIncludeTest: (value: boolean) => void;
  reload: () => Promise<void>;
  create: (input: IdeaCreateInput) => Promise<Idea>;
  setStatus: (id: string, toStatusId: string) => Promise<Idea>;
  vote: (id: string, dir: 'up') => Promise<Idea>;
  reorderPriority: (orderedIds: string[]) => Promise<void>;
  remove: (id: string) => Promise<void>;
  /** Collapse the given ideas onto `survivorId` (AC-94-21/22), then reload. */
  merge?: (survivorId: string, ideaIds: string[]) => Promise<Idea>;
  /** Restore a merged child (or dissolve a survivor's group), then reload. */
  unmerge?: (id: string) => Promise<Idea[]>;
}

/**
 * Loads + mutates the idea repository (plan: Phase A). The idea list AND the
 * triage board read ideas ONLY through this hook - the UI never touches the
 * service/api-client directly. Products load once alongside ideas (needed by the
 * capture modal's product picker).
 *
 * `withBoard` (issue #94, ideation round 2, AC-94-58) - opt-in: the list and
 * the form never need board columns, so they must never pay for the extra
 * `getBoard` request every reload. Only `TriageBoard` passes `true`.
 */
export function useIdeas(opts?: { withBoard?: boolean }): UseIdeas {
  const withBoard = opts?.withBoard ?? false;
  const { service: ideationService } = useIdeationRuntime();
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [includeTest, setIncludeTest] = useState(false);
  const [columns, setColumns] = useState<BoardColumn[] | undefined>(undefined);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextIdeas, nextProducts, board] = await Promise.all([
        // `filter: 'all'` (AC-94-60) - both active and archived survivors, so
        // the Archived view is fed; `selectIdeaRows` splits by the engine
        // trait `statusIsArchived`, never a hardcoded status key.
        ideationService.listIdeas({ includeTest, filter: 'all' }),
        ideationService.listProducts(),
        withBoard ? ideationService.getBoard?.({ includeTest }) : undefined,
      ]);
      setIdeas(nextIdeas);
      setProducts(nextProducts);
      setColumns(board?.columns);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load ideas.');
    } finally {
      setLoading(false);
    }
  }, [ideationService, includeTest, withBoard]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const create = useCallback(
    async (input: IdeaCreateInput) => {
      const created = await ideationService.createIdea(input);
      await reload();
      return created;
    },
    [reload, ideationService],
  );

  const setStatus = useCallback(
    async (id: string, toStatusId: string) => {
      const updated = await ideationService.setStatus(id, toStatusId);
      await reload();
      return updated;
    },
    [reload, ideationService],
  );

  const vote = useCallback(
    async (id: string, dir: 'up') => {
      const updated = await ideationService.vote(id, dir);
      await reload();
      return updated;
    },
    [reload, ideationService],
  );

  const reorderPriority = useCallback(
    async (orderedIds: string[]) => {
      await ideationService.reorderPriority(orderedIds);
      await reload();
    },
    [reload, ideationService],
  );

  const remove = useCallback(
    async (id: string) => {
      await ideationService.remove(id);
      await reload();
    },
    [reload, ideationService],
  );

  // Merge / unmerge (issue #94, ideation round 2) - optional on `IdeaService`
  // (a partial test double may omit them); the embed and operator services
  // both always implement them.
  const merge = useCallback(
    async (survivorId: string, ideaIds: string[]) => {
      if (!ideationService.merge) throw new Error('Merge is not available.');
      const survivor = await ideationService.merge(survivorId, ideaIds);
      await reload();
      return survivor;
    },
    [reload, ideationService],
  );

  const unmerge = useCallback(
    async (id: string) => {
      if (!ideationService.unmerge) throw new Error('Unmerge is not available.');
      const restored = await ideationService.unmerge(id);
      await reload();
      return restored;
    },
    [reload, ideationService],
  );

  return {
    ideas,
    products,
    loading,
    error,
    columns,
    includeTest,
    setIncludeTest,
    reload,
    create,
    setStatus,
    vote,
    reorderPriority,
    remove,
    merge,
    unmerge,
  };
}
