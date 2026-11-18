'use client';

/**
 * The done page after a broadcast is sent or scheduled, Foundryx UIUX switch
 * only (playbook 0.71.0 "When something is done"; answers Q3: done pages for
 * broadcast sends are the one approved workflow addition).
 *
 * Says what went out, to how many, by whom and when; one next step (the red
 * action "View delivery"), one way back (Broadcasts) and one open loop (the
 * delivery counts that come in later). Fits on one screen.
 */
import { useMemo } from 'react';
import Link from 'next/link';
import { Check, LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { useRegisterMainAction, type FxMainActionSpec } from '@/components/fx/actions/page-actions-context';
import { useBroadcast } from '@/hooks/use-broadcast';
import { useDatetime } from '@/hooks/use-datetime';
import type { Broadcast } from '@/types/omnichannel';
import type { BroadcastDoneEntry } from './broadcast-done-store';
import { contactsCount } from './fx-broadcast-actions';
import { broadcastsListPath } from './paths';

export interface BroadcastDoneLines {
  title: string;
  headline: string;
  detail: string;
  loop: string;
}

/** The done page's words (pure, tested). */
export function broadcastDoneLines(
  broadcast: Broadcast,
  entry: BroadcastDoneEntry,
  format: { dateTime: (iso: string) => string; time: (iso: string) => string },
): BroadcastDoneLines {
  const scheduled = entry.mode === 'schedule';
  const howMany = broadcast.counts.total > 0 ? broadcast.counts.total : entry.audienceCount;
  const to = howMany !== null ? ` to ${contactsCount(howMany)}` : '';
  const when = scheduled
    ? `Scheduled for ${format.dateTime(broadcast.scheduledAt ?? entry.pressedAt)}`
    : `Started at ${format.time(broadcast.startedAt ?? entry.pressedAt)}`;
  const by = entry.byWhom ? `, by ${entry.byWhom}` : '';
  return {
    title: scheduled ? 'Broadcast scheduled' : 'Broadcast sending',
    headline: `“${broadcast.name}” ${scheduled ? 'goes' : 'is going'}${to}`,
    detail: `${when} on ${broadcast.channelName} with the ${broadcast.templateName} template${by}.`,
    loop: scheduled
      ? 'Nothing goes out before then. Delivery counts show on the broadcast’s page once it sends.'
      : 'Delivery counts update on the broadcast’s page as they come in.',
  };
}

export interface BroadcastDoneViewProps {
  workspaceId: string | null;
  broadcastId: string;
  entry: BroadcastDoneEntry;
  /** Leaves the done page for the broadcast's own page (same address). */
  onViewDelivery: () => void;
}

export function BroadcastDoneView({ workspaceId, broadcastId, entry, onViewDelivery }: BroadcastDoneViewProps) {
  const { broadcast, loading } = useBroadcast(workspaceId, broadcastId);
  const { formatDateTime, formatTime } = useDatetime();

  const main = useMemo<FxMainActionSpec | null>(
    () =>
      broadcast
        ? {
            id: 'broadcast-view-delivery',
            label: 'View delivery',
            fullLabel: `View delivery of ${broadcast.name}`,
            onClick: onViewDelivery,
          }
        : null,
    [broadcast, onViewDelivery],
  );
  useRegisterMainAction(main);

  if (loading || !broadcast) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-(--fx-ink-3)">
          <LoaderCircleIcon className="size-6 animate-spin" aria-hidden="true" />
        </div>
      </Container>
    );
  }

  const lines = broadcastDoneLines(broadcast, entry, { dateTime: formatDateTime, time: formatTime });

  return (
    <Container width="fluid">
      <div className="flex flex-col gap-5">
        <PageHeader
          title={lines.title}
          crumbs={[
            { label: 'Omnichannel', href: broadcastsListPath },
            { label: 'Broadcasts', href: broadcastsListPath },
            { label: broadcast.name },
          ]}
        />
        <section
          data-fx-done=""
          className="mx-auto mt-2 flex w-full max-w-[640px] flex-col items-center gap-3.5 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) px-5 py-8 text-center sm:px-7"
        >
          <span className="grid size-14 place-items-center rounded-full bg-(--fx-ok-bg) text-(--fx-ok)">
            <Check className="size-6" strokeWidth={2.5} aria-hidden="true" />
          </span>
          <h2 className="break-words text-xl font-bold text-(--fx-ink)">{lines.headline}</h2>
          <p className="m-0 text-(--fx-ink-2)">{lines.detail}</p>
          <p className="m-0 rounded-(--fx-r-m) bg-(--fx-info-bg) px-3.5 py-2.5 text-sm text-(--fx-info-ink)">
            {lines.loop}
          </p>
          <Link
            href={broadcastsListPath}
            className="text-sm font-semibold text-(--fx-link) transition-[translate] duration-(--fx-t-hover) ease-(--fx-ease-out) hover:-translate-y-px"
          >
            Back to broadcasts
          </Link>
        </section>
      </div>
    </Container>
  );
}
