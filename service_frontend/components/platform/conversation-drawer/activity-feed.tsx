'use client';

/**
 * Merged Activities feed (plan 27, AC-IVE-32/34) - internal notes (existing
 * SYSTEM bubbles, reused as-is via `MessageBubble`) and conversation events
 * (compact system lines with actor + timestamp), sorted chronologically.
 * `comment_added` events are DELIBERATELY dropped (D-A3-4/AC-IVE-34) - the
 * note bubble already IS that activity; rendering both would duplicate it.
 */
import { Fragment, useMemo } from 'react';

import { dateKey, parseUtc } from '@/lib/datetime';
import type { ConversationEvent, ConversationMessage } from '@/types/omnichannel';

import { dayLabel } from './conversation-drawer';
import { MessageBubble } from './message-bubble';

export interface ActivityFeedProps {
  /** Every message for the thread - the feed filters to SYSTEM (notes) itself. */
  messages: ConversationMessage[];
  events: ConversationEvent[];
  contactName: string;
  formatTime: (iso: string) => string;
  timeZone?: string | null;
}

type FeedRow =
  | { kind: 'note'; createdAt: string; message: ConversationMessage }
  | { kind: 'event'; createdAt: string; event: ConversationEvent };

/** Human, tenant-facing sentence for one event line (no "Foundryx" copy, no
 *  how-to text - just what happened). */
function eventLine(event: ConversationEvent): string {
  const actor = event.actorName ?? 'System';
  switch (event.eventType) {
    case 'opened':
      return event.actorName ? `${actor} opened this conversation` : 'Conversation opened';
    case 'reopened':
      return event.actorName ? `${actor} reopened this conversation` : 'Conversation reopened';
    case 'snoozed':
      return `${actor} snoozed this conversation`;
    case 'unsnoozed':
      return `${actor} unsnoozed this conversation`;
    case 'closed':
      return event.closeReasonName
        ? `${actor} closed this conversation - ${event.closeReasonName}`
        : `${actor} closed this conversation`;
    case 'assigned':
      return event.toLabel ? `${actor} assigned to ${event.toLabel}` : `${actor} assigned this conversation`;
    case 'unassigned':
      return `${actor} removed the assignee`;
    case 'first_agent_reply':
      return `${actor} sent the first reply`;
    case 'lifecycle_changed':
      return event.fromLabel && event.toLabel
        ? `${actor} moved the lifecycle from ${event.fromLabel} to ${event.toLabel}`
        : `${actor} moved the lifecycle`;
    // `comment_added` is filtered out below BEFORE this ever runs (the note
    // bubble already IS that activity) - no case for it here, so a caller
    // reading this switch cannot mistake it for a live rendering path.
    default:
      return `${actor} updated this conversation`;
  }
}

export function ActivityFeed({ messages, events, contactName, formatTime, timeZone }: ActivityFeedProps) {
  const rows = useMemo<FeedRow[]>(() => {
    const notes: FeedRow[] = messages
      .filter((m) => m.senderType === 'SYSTEM')
      .map((message) => ({ kind: 'note', createdAt: message.createdAt, message }));
    const eventRows: FeedRow[] = events
      .filter((e) => e.eventType !== 'comment_added')
      .map((event) => ({ kind: 'event', createdAt: event.createdAt, event }));
    // F7 (round-3 codex triage) - a lexicographic string sort misorders ISO
    // timestamps with different fractional-second precision (e.g. Python's
    // `isoformat()` drops the fractional part entirely at exactly-zero
    // microseconds: `"...:00Z"` vs `"...:00.500000Z"` - the '.' (0x2E) sorts
    // BEFORE 'Z' (0x5A) character-by-character, so the LATER (.5s) timestamp
    // would sort FIRST). Compare the actual numeric epoch instead
    // (`parseUtc` - unparsable/missing sorts last, never crashes the feed).
    const epoch = (iso: string): number => parseUtc(iso)?.getTime() ?? Number.POSITIVE_INFINITY;
    return [...notes, ...eventRows].sort((a, b) => epoch(a.createdAt) - epoch(b.createdAt));
  }, [messages, events]);

  if (rows.length === 0) {
    return <p className="py-8 text-center text-sm text-muted-foreground">No activity yet.</p>;
  }

  return (
    <div className="flex flex-col gap-2.5" data-testid="activity-feed">
      {rows.map((row, i) => (
        <Fragment key={row.kind === 'note' ? row.message.id : row.event.id}>
          {(i === 0 || dateKey(rows[i - 1].createdAt, { timeZone }) !== dateKey(row.createdAt, { timeZone })) && (
            <div className="flex justify-center py-1">
              <span className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground shadow-xs">
                {dayLabel(row.createdAt, new Date(), timeZone)}
              </span>
            </div>
          )}
          {row.kind === 'note' ? (
            <MessageBubble message={row.message} contactName={contactName} formatTime={formatTime} />
          ) : (
            <div
              className="flex items-center justify-center gap-2 py-0.5 text-center text-xs text-muted-foreground"
              data-testid={`event-${row.event.eventType}`}
            >
              <span>{eventLine(row.event)}</span>
              <span className="shrink-0">{formatTime(row.event.createdAt)}</span>
            </div>
          )}
        </Fragment>
      ))}
    </div>
  );
}
