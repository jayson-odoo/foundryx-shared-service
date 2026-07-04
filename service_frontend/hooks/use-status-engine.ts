'use client';

/**
 * Status-engine state (sprint-2/01) — `useStatusEntities` backs the entity
 * LIST surface; `useStatusGraph(entityType)` backs one entity's detail form
 * (canvas + statuses tab) with mutation helpers that refetch on success.
 * Position saves are SILENT (no refetch — the canvas already shows the node
 * where the user dropped it; a refetch would make dragging feel janky).
 */
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { ApiError } from '@/lib/api-client';
import { statusEngineService } from '@/services/status-engine-service';
import type {
  CreateStatusInput,
  CreateTransitionInput,
  StatusEntity,
  StatusGraph,
  UpdateStatusInput,
  UpdateTransitionInput,
} from '@/types/status-engine';

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Something went wrong. Please try again.';
}

export interface UseStatusEntitiesResult {
  entities: StatusEntity[];
  loading: boolean;
  refresh: () => Promise<void>;
}

export function useStatusEntities(): UseStatusEntitiesResult {
  const [entities, setEntities] = useState<StatusEntity[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setEntities(await statusEngineService.entities());
    } catch (error) {
      toast.error(describe(error));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    statusEngineService
      .entities()
      .then((data) => !cancelled && setEntities(data))
      .catch((error) => toast.error(describe(error)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  return { entities, loading, refresh };
}

export interface UseStatusGraphResult {
  graph: StatusGraph | null;
  loading: boolean;
  refresh: () => Promise<void>;
  createStatus: (input: CreateStatusInput) => Promise<boolean>;
  updateStatus: (id: string, input: UpdateStatusInput) => Promise<boolean>;
  /** Canvas drag-stop — persists silently, never refetches (smooth drag). */
  saveNodePosition: (id: string, x: number, y: number) => void;
  deleteStatus: (id: string) => Promise<boolean>;
  setStatusActive: (id: string, active: boolean) => Promise<boolean>;
  migrateRecords: (id: string, toStatusId: string) => Promise<boolean>;
  reorder: (orderedIds: string[]) => Promise<boolean>;
  createTransition: (input: CreateTransitionInput) => Promise<boolean>;
  updateTransition: (id: string, input: UpdateTransitionInput) => Promise<boolean>;
  deleteTransition: (id: string) => Promise<boolean>;
}

/** `scopeId` = scoped machines (sprint-3/01 D4): the graph of ONE owning
 * record (e.g. a form's submission pipeline); create calls carry the scope. */
export function useStatusGraph(
  entityType: string | null,
  scopeId?: string,
): UseStatusGraphResult {
  const [graph, setGraph] = useState<StatusGraph | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!entityType) return;
    try {
      setGraph(await statusEngineService.graph(entityType, scopeId));
    } catch (error) {
      toast.error(describe(error));
    }
  }, [entityType, scopeId]);

  useEffect(() => {
    if (!entityType) {
      setLoading(false); // never strand consumers on a permanent spinner
      return;
    }
    let cancelled = false;
    setLoading(true);
    statusEngineService
      .graph(entityType, scopeId)
      .then((data) => !cancelled && setGraph(data))
      .catch((error) => toast.error(describe(error)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [entityType, scopeId]);

  /** Run a mutation, toast failures, refetch the graph on success. */
  const mutate = useCallback(
    async (action: () => Promise<unknown>, successMessage?: string) => {
      try {
        await action();
        if (successMessage) toast.success(successMessage);
        await refresh();
        return true;
      } catch (error) {
        toast.error(describe(error));
        return false;
      }
    },
    [refresh],
  );

  const saveNodePosition = useCallback((id: string, x: number, y: number) => {
    // Fire-and-forget on purpose: the node is already where the user put it.
    statusEngineService
      .updateStatus(id, { positionX: x, positionY: y })
      .catch((error) => toast.error(describe(error)));
  }, []);

  return {
    graph,
    loading,
    refresh,
    createStatus: (input) =>
      // Scoped graphs: every created status belongs to THIS scope (D4).
      mutate(
        () => statusEngineService.createStatus(scopeId ? { ...input, scopeId } : input),
        'Status created.',
      ),
    updateStatus: (id, input) => mutate(() => statusEngineService.updateStatus(id, input)),
    saveNodePosition,
    deleteStatus: (id) =>
      mutate(() => statusEngineService.deleteStatus(id), 'Status deleted.'),
    setStatusActive: (id, active) =>
      mutate(
        () => statusEngineService.setStatusActive(id, active),
        active ? 'Status activated.' : 'Status deactivated.',
      ),
    migrateRecords: (id, toStatusId) =>
      mutate(() => statusEngineService.migrateRecords(id, toStatusId), 'Records migrated.'),
    reorder: (orderedIds) =>
      mutate(() => statusEngineService.reorder(entityType ?? '', orderedIds)),
    createTransition: (input) =>
      mutate(
        () => statusEngineService.createTransition(scopeId ? { ...input, scopeId } : input),
        'Transition created.',
      ),
    updateTransition: (id, input) => mutate(() => statusEngineService.updateTransition(id, input)),
    deleteTransition: (id) =>
      mutate(() => statusEngineService.deleteTransition(id), 'Transition deleted.'),
  };
}
