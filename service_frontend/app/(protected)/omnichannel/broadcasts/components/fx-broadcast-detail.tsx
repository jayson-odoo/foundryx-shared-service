'use client';

/**
 * The broadcast page (an existing broadcast) under the Foundryx UIUX switch
 * (playbook 0.71.0; build plan W2-BCAST). Same hooks, same requests and the
 * same two tabs as the switch-off page; what changes is the look:
 *
 * - Send now is the red action in the page header ("Send now to 23 contacts
 *   with promo_nov_2026" on hover), only while the broadcast can still be
 *   sent; Edit, Send test message, Duplicate, Cancel and Delete are icon
 *   actions beside it. Editing a draft opens the same form as today.
 * - The delivery counts roll to their new values as the live updates arrive,
 *   and the progress bar eases with them (gap audit "Lists and numbers that
 *   update by themselves").
 * - Both tabs stay mounted, so the Recipients list keeps its place.
 */
import { useCallback, useMemo, useState } from 'react';
import Link from 'next/link';
import { LayoutList, ListChecks, LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Form } from '@/components/ui/form';
import { ResourceForm, type FormTab, type ResourceFormConfig } from '@/components/platform/resource-form';
import { ResourceList, type ResourceAction } from '@/components/platform/resource-list';
import { ClampedText } from '@/components/platform/clamped-text';
import { useConversationSocket } from '@/hooks/use-conversation-socket';
import { useDatetime } from '@/hooks/use-datetime';
import type { Broadcast, BroadcastCounts, ConversationSocketEvent } from '@/types/omnichannel';
import { useBroadcastForm } from './use-broadcast-form';
import { DetailStatusChip, TestSendDialog } from './broadcast-form-sections';
import { BuilderSections } from './broadcast-form-view';
import { matchBroadcastUpdate } from './broadcast-realtime';
import { useRecipientsListConfig } from './use-recipients-list-config';
import { broadcastsListPath } from './paths';
import { fxSendNowLabel } from './fx-broadcast-words';
import { FxRollingCount } from './fx-rolling-count';

const COUNTS: { key: keyof BroadcastCounts; label: string }[] = [
  { key: 'total', label: 'Total' },
  { key: 'sent', label: 'Sent' },
  { key: 'delivered', label: 'Delivered' },
  { key: 'read', label: 'Read' },
  { key: 'failed', label: 'Failed' },
  { key: 'skipped', label: 'Skipped' },
];

/** How far the send has got, 0 to 100: every recipient tried (sent, failed or
 *  skipped) out of the total. */
export function deliveryProgress(counts: BroadcastCounts): number {
  if (!counts.total) return 0;
  const done = counts.sent + counts.failed + counts.skipped;
  return Math.min(100, Math.round((done / counts.total) * 100));
}

/** The status card, with counts that roll as live updates arrive. */
export function FxBroadcastStatus({ broadcast }: { broadcast: Broadcast }) {
  const { formatDateTime } = useDatetime();
  const progress = deliveryProgress(broadcast.counts);
  const moments: { label: string; iso: string | null }[] = [
    { label: 'Scheduled for', iso: broadcast.scheduledAt },
    { label: 'Started', iso: broadcast.startedAt },
    { label: 'Finished', iso: broadcast.finishedAt },
  ];
  return (
    <section
      aria-label="Delivery"
      data-fx-broadcast-status=""
      className="flex flex-col gap-4 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-4 sm:p-5"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-base font-semibold text-(--fx-ink)">Delivery</h3>
        <DetailStatusChip status={broadcast.status} />
      </div>
      <dl className="grid grid-cols-3 gap-x-4 gap-y-3 sm:grid-cols-6">
        {COUNTS.map(({ key, label }) => (
          <div key={key} className="flex flex-col gap-0.5">
            <dt className="text-xs text-(--fx-ink-3)">{label}</dt>
            <dd
              className={
                key === 'failed' && broadcast.counts.failed > 0
                  ? 'text-lg font-semibold text-(--fx-act)'
                  : 'text-lg font-semibold text-(--fx-ink)'
              }
            >
              <FxRollingCount value={broadcast.counts[key]} />
            </dd>
          </div>
        ))}
      </dl>
      {broadcast.counts.total > 0 && (
        <div
          role="progressbar"
          aria-label="Recipients tried"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress}
          className="h-1.5 w-full overflow-hidden rounded-(--fx-r-pill) bg-(--fx-surface-2)"
        >
          <div
            className="h-full rounded-(--fx-r-pill) bg-(--fx-link) transition-[width] duration-(--fx-t-layout) ease-(--fx-ease-out) motion-reduce:transition-none"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}
      {moments.some((m) => m.iso) && (
        <dl className="flex flex-col gap-2 border-t border-(--fx-line) pt-3 text-sm">
          {moments.map((m) =>
            m.iso ? (
              <div key={m.label} className="flex justify-between gap-4">
                <dt className="text-(--fx-ink-3)">{m.label}</dt>
                <dd className="tabular-nums text-(--fx-ink)">{formatDateTime(m.iso)}</dd>
              </div>
            ) : null,
          )}
        </dl>
      )}
      {broadcast.error && (
        <div className="rounded-(--fx-r-m) bg-(--fx-warn-bg) p-3 text-sm text-(--fx-warn-ink)">
          <ClampedText text={broadcast.error} lines={3} />
        </div>
      )}
    </section>
  );
}

export interface FxBroadcastDetailViewProps {
  workspaceId: string | null;
  broadcastId: string;
  initialEditing: boolean;
}

export function FxBroadcastDetailView({ workspaceId, broadcastId, initialEditing }: FxBroadcastDetailViewProps) {
  const {
    config,
    form,
    isLoading,
    notFound,
    broadcast,
    creating,
    ensureDraftId,
    sendOrSchedule,
    sending,
    refresh,
  } = useBroadcastForm(workspaceId, broadcastId, initialEditing);

  const { config: recipientsConfig, reload: reloadRecipients, reloadToken } = useRecipientsListConfig(
    workspaceId,
    broadcast?.id ?? null,
  );

  // The same live wiring as the switch-off page: a matching frame refetches
  // the broadcast and its Recipients list (no polling).
  const activeBroadcastId = broadcast?.id;
  const onSocketEvent = useCallback(
    (event: ConversationSocketEvent) => {
      if (!matchBroadcastUpdate(event, activeBroadcastId)) return;
      void refresh();
      reloadRecipients();
    },
    [activeBroadcastId, refresh, reloadRecipients],
  );
  useConversationSocket(workspaceId, onSocketEvent);

  // Send test message: today an outline button on the page once the
  // broadcast has left Draft; here the same dialog from a header icon.
  const [testOpen, setTestOpen] = useState(false);
  const testAction = useMemo<ResourceAction<Broadcast>>(
    () => ({
      id: 'test-message',
      label: 'Send test message',
      permission: 'broadcasts.send',
      surfaces: { form: true },
      isVisible: (rows) => rows.length === 1 && rows[0].status !== 'DRAFT',
      run: () => setTestOpen(true),
    }),
    [],
  );

  const fullConfig = useMemo<ResourceFormConfig<Broadcast> | null>(() => {
    if (!config) return null;
    const sendAt = config.actions.findIndex((a) => a.id === 'send');
    const actions = [...config.actions];
    actions.splice(sendAt + 1, 0, testAction);
    const overviewTab: FormTab = {
      id: 'overview',
      label: 'Overview',
      icon: LayoutList,
      render: ({ editing }) => (
        <BuilderSections
          workspaceId={workspaceId}
          editing={editing}
          form={form}
          broadcast={broadcast}
          creating={creating}
          ensureDraftId={ensureDraftId}
          sendOrSchedule={sendOrSchedule}
          sending={sending}
          fxStatus={broadcast ? <FxBroadcastStatus broadcast={broadcast} /> : undefined}
          fxTestInHeader
        />
      ),
    };
    const recipientsTab: FormTab = {
      id: 'recipients',
      label: 'Recipients',
      icon: ListChecks,
      render: () => <ResourceList key={reloadToken} config={recipientsConfig} hideHeader />,
    };
    return {
      ...config,
      actions,
      tabs: [overviewTab, recipientsTab],
      initialTabId: 'overview',
      fx: {
        mainActionId: 'send',
        fullLabel: fxSendNowLabel,
        iconFor: {
          'form-edit': 'edit',
          'test-message': 'test-message',
          duplicate: 'copy',
          delete: 'trash',
        },
        discardName: broadcast?.name,
      },
    };
  }, [
    config,
    testAction,
    workspaceId,
    form,
    broadcast,
    creating,
    ensureDraftId,
    sendOrSchedule,
    sending,
    recipientsConfig,
    reloadToken,
  ]);

  if (isLoading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-(--fx-ink-3)">
          <LoaderCircleIcon className="size-6 animate-spin" aria-hidden="true" />
        </div>
      </Container>
    );
  }

  if (notFound || !fullConfig) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium text-(--fx-ink)">Broadcast not found.</p>
          <Link
            href={broadcastsListPath}
            className="text-sm font-semibold text-(--fx-link) transition-[translate] duration-(--fx-t-hover) ease-(--fx-ease-out) hover:-translate-y-px"
          >
            Back to broadcasts
          </Link>
        </div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={fullConfig} />
      </Form>
      {broadcast && (
        <TestSendDialog
          open={testOpen}
          onOpenChange={setTestOpen}
          workspaceId={workspaceId}
          ensureBroadcastId={async () => broadcast.id}
        />
      )}
    </Container>
  );
}
