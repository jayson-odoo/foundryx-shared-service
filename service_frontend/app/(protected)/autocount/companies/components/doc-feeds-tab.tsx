'use client';

import { useCallback, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { toast } from '@/lib/toast';
import { ResourceList } from '@/components/platform/resource-list';
import { useAutocountDocFeeds } from '@/hooks/use-autocount-doc-feeds';
import { autocountService } from '@/services/autocount-service';
import type { DocFeedBackfillStartInput, DocFeedKey, DocFeedUpdateInput } from '@/types/autocount';
import { DocFeedBackfillDialog } from './doc-feed-backfill-dialog';
import { DocFeedConfigDialog } from './doc-feed-config-dialog';
import { useDocFeedIssuesListConfig } from './use-doc-feed-issues-list-config';
import { useDocFeedRunsListConfig } from './use-doc-feed-runs-list-config';
import { useDocFeedsListConfig } from './use-doc-feeds-list-config';

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

/**
 * "Document feeds" company detail tab (sprint-5/14, D17, AC-14-90..95) - the
 * DO / GRN / branch HTTP source's whole operator surface: three feed rows,
 * their run history, their waiting/failed documents, and the Configure /
 * Backfill dialogs. Every call goes through `autocountService`, bound to the
 * real `/autocount/doc-feeds/*` router.
 */
export function DocFeedsTab({ companyId }: { companyId: string }) {
  const { view, reload } = useAutocountDocFeeds(companyId);
  const [configuring, setConfiguring] = useState<DocFeedKey | null>(null);
  const [backfilling, setBackfilling] = useState<DocFeedKey | null>(null);
  // The Runs/Issues embedded lists own their OWN fetch (the resource-list
  // shell has no cross-list "someone else changed the data" signal) - a
  // bumped key remounts them after any action that could add a run or issue
  // row, the SAME `runsKey` pattern `company-detail-view.tsx`'s own Runs tab
  // uses after a sync.
  const [listsKey, setListsKey] = useState(0);
  const refreshAll = useCallback(async () => {
    await reload();
    setListsKey((k) => k + 1);
  }, [reload]);

  const feeds = view?.feeds ?? [];
  const eligibleConnections = view?.eligibleConnections ?? [];

  const runNow = useCallback(
    async (feed: DocFeedKey, kind: 'poll' | 'sweep') => {
      try {
        await autocountService.runDocFeed(companyId, feed, { kind });
        toast.success(kind === 'sweep' ? 'Re-check started.' : 'Run started.');
        await refreshAll();
      } catch (error) {
        toast.error(errorMessage(error, 'That run could not be started.'));
      }
    },
    [companyId, refreshAll],
  );

  const stopBackfill = useCallback(
    async (feed: DocFeedKey) => {
      try {
        await autocountService.stopDocFeedBackfill(companyId, feed);
        toast.success('Backfill stopped.');
        await refreshAll();
      } catch (error) {
        toast.error(errorMessage(error, 'That backfill could not be stopped.'));
      }
    },
    [companyId, refreshAll],
  );

  const resumeBackfill = useCallback(
    async (feed: DocFeedKey) => {
      try {
        await autocountService.resumeDocFeedBackfill(companyId, feed);
        toast.success('Backfill resumed.');
        await refreshAll();
      } catch (error) {
        toast.error(errorMessage(error, 'That backfill could not be resumed.'));
      }
    },
    [companyId, refreshAll],
  );

  const discardBackfill = useCallback(
    async (feed: DocFeedKey) => {
      try {
        await autocountService.discardDocFeedBackfill(companyId, feed);
        toast.success('Backfill discarded.');
        await refreshAll();
      } catch (error) {
        toast.error(errorMessage(error, 'That backfill could not be discarded.'));
      }
    },
    [companyId, refreshAll],
  );

  const feedsConfig = useDocFeedsListConfig({
    feeds,
    onConfigure: setConfiguring,
    onRunNow: (feed) => void runNow(feed, 'poll'),
    onRunSweepNow: (feed) => void runNow(feed, 'sweep'),
    onBackfill: setBackfilling,
    onStopBackfill: (feed) => void stopBackfill(feed),
    onResumeBackfill: (feed) => void resumeBackfill(feed),
    onDiscardBackfill: (feed) => void discardBackfill(feed),
  });
  const runsConfig = useDocFeedRunsListConfig(companyId);
  const issuesConfig = useDocFeedIssuesListConfig(companyId);

  const configuringItem = feeds.find((f) => f.feed === configuring) ?? null;
  const backfillingItem = feeds.find((f) => f.feed === backfilling) ?? null;

  const saveConfig = useCallback(
    async (feed: DocFeedKey, input: DocFeedUpdateInput) => {
      try {
        await autocountService.updateDocFeed(companyId, feed, input);
        toast.success('Document feed updated.');
        setConfiguring(null);
        await refreshAll();
      } catch (error) {
        toast.error(errorMessage(error, 'That could not be saved.'));
        // Rethrown so the dialog stays open and shows any per-field 422.
        throw error;
      }
    },
    [companyId, refreshAll],
  );

  const startBackfill = useCallback(
    async (feed: DocFeedKey, input: DocFeedBackfillStartInput) => {
      try {
        await autocountService.startDocFeedBackfill(companyId, feed, input);
        toast.success('Backfill started.');
        await refreshAll();
      } catch (error) {
        toast.error(errorMessage(error, 'That backfill could not be started.'));
      }
    },
    [companyId, refreshAll],
  );

  return (
    <div className="flex flex-col gap-6 py-2">
      <ResourceList config={feedsConfig} hideHeader />
      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-medium text-foreground">Runs</h3>
        <ResourceList key={listsKey} config={runsConfig} hideHeader />
      </div>
      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-medium text-foreground">Waiting and failed documents</h3>
        <ResourceList key={listsKey} config={issuesConfig} hideHeader />
      </div>
      {configuringItem && (
        <DocFeedConfigDialog
          feed={configuringItem.feed}
          current={{
            connectionId: configuringItem.connectionId,
            mode: configuringItem.mode,
            contractGate: configuringItem.contractGate,
            schedule: configuringItem.schedule,
            window: configuringItem.window,
            nextPollAt: configuringItem.nextPollAt,
            nextSweepAt: configuringItem.nextSweepAt,
          }}
          eligibleConnections={eligibleConnections}
          onClose={() => setConfiguring(null)}
          onSave={(input) => saveConfig(configuringItem.feed, input)}
        />
      )}
      {backfillingItem && (
        <DocFeedBackfillDialog
          feed={backfillingItem.feed}
          mode={backfillingItem.mode}
          fullBackfillDoneAt={backfillingItem.fullBackfillDoneAt}
          backfill={
            backfillingItem.backfill
              ? {
                  status: backfillingItem.backfill.status,
                  daysDone: backfillingItem.backfill.daysDone,
                  daysTotal: backfillingItem.backfill.daysTotal,
                  dryRun: backfillingItem.backfill.dryRun,
                }
              : null
          }
          onClose={() => setBackfilling(null)}
          onStart={(input) => startBackfill(backfillingItem.feed, input)}
          onStop={() => stopBackfill(backfillingItem.feed)}
        />
      )}
    </div>
  );
}
