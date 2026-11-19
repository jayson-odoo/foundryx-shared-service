'use client';

/**
 * The Activities feed under the Foundryx UIUX switch (W1-CONV): the same
 * notes and events in the same order, with the playbook's day lines
 * ("Today", "Yesterday", "14 Nov 2026") and 12-hour times.
 */
import { Fragment, useMemo } from 'react';
import { dateKey } from '@/lib/datetime';
import { FxDayLine } from '@/components/fx/fields/fx-moment';
import {
  buildFeedRows,
  eventLine,
  type ActivityFeedProps,
} from '../activity-feed';
import { MessageBubble } from '../message-bubble';

export function FxActivityFeed({
  messages,
  events,
  contactName,
  formatTime,
  timeZone,
}: ActivityFeedProps) {
  const rows = useMemo(
    () => buildFeedRows(messages, events),
    [messages, events],
  );

  if (rows.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-(--fx-ink-3)">
        No activity yet.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2.5" data-testid="activity-feed">
      {rows.map((row, i) => (
        <Fragment key={row.kind === 'note' ? row.message.id : row.event.id}>
          {(i === 0 ||
            dateKey(rows[i - 1].createdAt, { timeZone }) !==
              dateKey(row.createdAt, { timeZone })) && (
            <FxDayLine iso={row.createdAt} />
          )}
          {row.kind === 'note' ? (
            <MessageBubble
              message={row.message}
              contactName={contactName}
              formatTime={formatTime}
            />
          ) : (
            <div
              className="flex items-center justify-center gap-2 py-0.5 text-center text-xs text-(--fx-ink-3)"
              data-testid={`event-${row.event.eventType}`}
            >
              <span>{eventLine(row.event)}</span>
              <span className="shrink-0 tabular-nums">
                {formatTime(row.event.createdAt)}
              </span>
            </div>
          )}
        </Fragment>
      ))}
    </div>
  );
}
