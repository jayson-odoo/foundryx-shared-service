'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  MigrationSyncAction,
  MigrationSyncItem,
} from '@/types/respondio-migration';
import { ApiError } from '@/lib/api-client';
import { toast } from '@/lib/toast';
import { respondioMigrationService } from '@/services/respondio-migration-service';

/** Poll fast while a tick is running, slowly otherwise (plan 52 section 5). */
export const SYNC_POLL_RUNNING_MS = 5000;
export const SYNC_POLL_IDLE_MS = 30000;

export interface UseMigrationSyncResult {
  /** `null` = no sync yet (or not loaded). */
  sync: MigrationSyncItem | null;
  loaded: boolean;
  /** An action request is in flight. */
  busy: boolean;
  /** Full webhook URL; only fetched for `canManage`. */
  webhookUrl: string | null;
  start: () => Promise<void>;
  act: (action: MigrationSyncAction) => Promise<void>;
}

function messageOf(err: unknown, fallback: string): string {
  return err instanceof ApiError && err.message ? err.message : fallback;
}

export function useMigrationSync(
  workspaceId: string,
  canManage: boolean,
): UseMigrationSyncResult {
  const [sync, setSync] = useState<MigrationSyncItem | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [webhookUrl, setWebhookUrl] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);

  const load = useCallback(async (): Promise<MigrationSyncItem | null> => {
    try {
      const item = await respondioMigrationService.getSync(workspaceId);
      if (alive.current) {
        setSync(item);
        setLoaded(true);
      }
      return item;
    } catch (err) {
      if (alive.current) {
        setLoaded(true);
        toast.error(messageOf(err, 'Could not load the sync status.'));
      }
      return null;
    }
  }, [workspaceId]);

  // Poll loop: 5 s while a tick runs, else 30 s. Re-armed after every load.
  useEffect(() => {
    alive.current = true;
    const loop = async () => {
      const item = await load();
      if (!alive.current) return;
      const wait = item?.runningJobId
        ? SYNC_POLL_RUNNING_MS
        : SYNC_POLL_IDLE_MS;
      timer.current = setTimeout(loop, wait);
    };
    void loop();
    return () => {
      alive.current = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [load]);

  // After an action the poll cadence may need to change: restart the loop.
  const restartPoll = useCallback(
    (item: MigrationSyncItem) => {
      if (timer.current) clearTimeout(timer.current);
      const wait = item.runningJobId ? SYNC_POLL_RUNNING_MS : SYNC_POLL_IDLE_MS;
      timer.current = setTimeout(async function again() {
        const next = await load();
        if (!alive.current) return;
        timer.current = setTimeout(
          again,
          next?.runningJobId ? SYNC_POLL_RUNNING_MS : SYNC_POLL_IDLE_MS,
        );
      }, wait);
    },
    [load],
  );

  const syncId = sync?.id ?? null;
  const showsWebhook =
    canManage && syncId !== null && sync?.status !== 'stopped';
  useEffect(() => {
    if (!showsWebhook || !syncId) {
      setWebhookUrl(null);
      return;
    }
    let cancelled = false;
    respondioMigrationService
      .getSyncWebhook(syncId)
      .then((w) => {
        if (!cancelled) setWebhookUrl(w.url);
      })
      .catch(() => {
        if (!cancelled) setWebhookUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [showsWebhook, syncId]);

  const run = useCallback(
    async (call: () => Promise<MigrationSyncItem>, failure: string) => {
      setBusy(true);
      try {
        const item = await call();
        if (alive.current) {
          setSync(item);
          restartPoll(item);
        }
      } catch (err) {
        toast.error(messageOf(err, failure));
      } finally {
        if (alive.current) setBusy(false);
      }
    },
    [restartPoll],
  );

  const start = useCallback(
    () =>
      run(
        () => respondioMigrationService.createSync(workspaceId),
        'Could not start syncing.',
      ),
    [run, workspaceId],
  );

  const act = useCallback(
    async (action: MigrationSyncAction) => {
      if (!syncId) return;
      await run(
        () => respondioMigrationService.syncAction(syncId, action),
        'That action did not go through.',
      );
    },
    [run, syncId],
  );

  return { sync, loaded, busy, webhookUrl, start, act };
}
