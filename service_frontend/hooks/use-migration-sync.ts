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
  /** The stored webhook link cannot be read; rotating it fixes that. */
  webhookUnreadable: boolean;
  start: () => Promise<void>;
  act: (action: MigrationSyncAction) => Promise<void>;
  rotateWebhook: () => Promise<void>;
}

/** Plain copy for the 409 reasons the sync routes answer. */
const REASON_COPY: Record<string, string> = {
  tick_running: 'A sync is already running. Try again when it finishes.',
  sync_exists: 'A sync already exists for this workspace.',
  no_finished_migration: 'Finish a migration for this workspace first.',
  webhook_unreadable: 'The webhook link could not be read.',
  migration_in_progress: 'A migration is running for this workspace.',
  not_active: 'This sync is not active.',
  not_paused: 'This sync is not paused.',
};

export function syncErrorCopy(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const detail = err.detail as { reason?: unknown } | null | undefined;
    const reason = typeof detail?.reason === 'string' ? detail.reason : null;
    if (reason && REASON_COPY[reason]) return REASON_COPY[reason];
    if (err.status === 409) return fallback;
    if (err.message) return err.message;
  }
  return fallback;
}

function nextWait(item: MigrationSyncItem | null): number {
  return item?.runningJobId ? SYNC_POLL_RUNNING_MS : SYNC_POLL_IDLE_MS;
}

export function useMigrationSync(
  workspaceId: string,
  canManage: boolean,
): UseMigrationSyncResult {
  const [sync, setSync] = useState<MigrationSyncItem | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [webhookUrl, setWebhookUrl] = useState<string | null>(null);
  const [webhookUnreadable, setWebhookUnreadable] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const generation = useRef(0);
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
        toast.error(syncErrorCopy(err, 'Could not load the sync status.'));
      }
      return null;
    }
  }, [workspaceId]);

  // ONE poll chain: scheduling always clears the previous timer and bumps a
  // generation, so a late-resolving load of an older chain can never re-arm.
  const schedule = useCallback(
    (delay: number) => {
      if (timer.current) clearTimeout(timer.current);
      const gen = ++generation.current;
      timer.current = setTimeout(async () => {
        if (gen !== generation.current) return;
        const item = await load();
        if (!alive.current || gen !== generation.current) return;
        schedule(nextWait(item));
      }, delay);
    },
    [load],
  );

  useEffect(() => {
    alive.current = true;
    schedule(0);
    return () => {
      alive.current = false;
      generation.current += 1;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [schedule]);

  const syncId = sync?.id ?? null;
  const showsWebhook =
    canManage && syncId !== null && sync?.status !== 'stopped';
  useEffect(() => {
    if (!showsWebhook || !syncId) {
      setWebhookUrl(null);
      setWebhookUnreadable(false);
      return;
    }
    let cancelled = false;
    respondioMigrationService
      .getSyncWebhook(syncId)
      .then((w) => {
        if (cancelled) return;
        setWebhookUrl(w.url);
        setWebhookUnreadable(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setWebhookUrl(null);
        const detail =
          err instanceof ApiError
            ? (err.detail as { reason?: unknown } | null)
            : null;
        setWebhookUnreadable(detail?.reason === 'webhook_unreadable');
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
          schedule(nextWait(item));
        }
      } catch (err) {
        toast.error(syncErrorCopy(err, failure));
      } finally {
        if (alive.current) setBusy(false);
      }
    },
    [schedule],
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

  const rotateWebhook = useCallback(async () => {
    if (!syncId) return;
    setBusy(true);
    try {
      const w = await respondioMigrationService.rotateSyncWebhook(syncId);
      if (alive.current) {
        setWebhookUrl(w.url);
        setWebhookUnreadable(false);
      }
    } catch (err) {
      toast.error(syncErrorCopy(err, 'Could not rotate the link.'));
    } finally {
      if (alive.current) setBusy(false);
    }
  }, [syncId]);

  return {
    sync,
    loaded,
    busy,
    webhookUrl,
    webhookUnreadable,
    start,
    act,
    rotateWebhook,
  };
}
