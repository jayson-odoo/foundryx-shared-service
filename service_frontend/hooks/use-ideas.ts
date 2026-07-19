'use client';

import { useCallback, useEffect, useState } from 'react';
import { ideationService, type IdeaCreateInput } from '@/services/ideation-service';
import type { Idea, IdeaStatus, Product } from '@/types/ideation';

export interface UseIdeas {
  ideas: Idea[];
  products: Product[];
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  create: (input: IdeaCreateInput) => Promise<Idea>;
  setStatus: (id: string, status: IdeaStatus) => Promise<Idea>;
  vote: (id: string, dir: 'up' | 'down') => Promise<Idea>;
  reorderPriority: (orderedIds: string[]) => Promise<void>;
  remove: (id: string) => Promise<void>;
}

/**
 * Loads + mutates the idea repository (plan: Phase A). The idea list AND the
 * triage board read ideas ONLY through this hook — the UI never touches the
 * service/api-client directly. Products load once alongside ideas (needed by the
 * capture modal's product picker).
 */
export function useIdeas(): UseIdeas {
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextIdeas, nextProducts] = await Promise.all([
        ideationService.listIdeas(),
        ideationService.listProducts(),
      ]);
      setIdeas(nextIdeas);
      setProducts(nextProducts);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load ideas.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const create = useCallback(
    async (input: IdeaCreateInput) => {
      const created = await ideationService.createIdea(input);
      await reload();
      return created;
    },
    [reload],
  );

  const setStatus = useCallback(
    async (id: string, status: IdeaStatus) => {
      const updated = await ideationService.setStatus(id, status);
      await reload();
      return updated;
    },
    [reload],
  );

  const vote = useCallback(
    async (id: string, dir: 'up' | 'down') => {
      const updated = await ideationService.vote(id, dir);
      await reload();
      return updated;
    },
    [reload],
  );

  const reorderPriority = useCallback(
    async (orderedIds: string[]) => {
      await ideationService.reorderPriority(orderedIds);
      await reload();
    },
    [reload],
  );

  const remove = useCallback(
    async (id: string) => {
      await ideationService.remove(id);
      await reload();
    },
    [reload],
  );

  return { ideas, products, loading, error, reload, create, setStatus, vote, reorderPriority, remove };
}
