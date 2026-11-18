'use client';

/**
 * The inbox thread list with the Foundryx UIUX switch on (slice W1-INBOX).
 * Same data, same search field and same selection as the legacy list; only
 * how it is drawn and how it moves differ:
 * - relative times through `useDatetime()` ("now", "5 min", "Yesterday"),
 *   with the full 12-hour moment as the tooltip;
 * - rows lift on hover and the open one carries the link tint;
 * - while the pointer is on the list or it is scrolled down, rows never move
 *   under it: a "3 new" pill at its top edge shows the live order instead
 *   (gap audit 15, owner choice);
 * - loading, nothing here, nothing matches and couldn't load say what to do.
 * No hover-widen: the list keeps its width (owner choice).
 */
import { useRef, useState, type ReactNode } from 'react';
import { ArrowUp, MessagesSquare, Search, TriangleAlert } from 'lucide-react';
import type { ConversationThread } from '@/types/omnichannel';
import { channelCapabilities } from '@/lib/channel-capabilities';
import { cn } from '@/lib/utils';
import {
  DEFAULT_FILTERS,
  type ConversationFilters,
} from '@/hooks/use-conversations';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { Skeleton } from '@/components/ui/skeleton';
import { FxMoment } from '@/components/fx/fields/fx-moment';
import {
  THREAD_PRIORITY_REGISTRY,
  THREAD_STATUS_REGISTRY,
} from '@/components/platform/conversation-drawer';
import {
  StatusBadge,
  type StatusRegistry,
} from '@/components/platform/status-badge';
import type { ThreadListProps } from '../thread-list';
import { useHeldThreads } from './held-threads';

function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('');
}

/** Whether any filter narrows the list (the rail, the bar or the search). */
export function fxInboxFiltered(filters: ConversationFilters): boolean {
  return (
    filters.assignee !== DEFAULT_FILTERS.assignee ||
    filters.status !== DEFAULT_FILTERS.status ||
    filters.priority !== DEFAULT_FILTERS.priority ||
    filters.search.trim() !== '' ||
    filters.lifecycleStageIds.length > 0 ||
    filters.tagIds.length > 0 ||
    filters.channelIds.length > 0 ||
    filters.unreplied ||
    !!filters.viewId ||
    !!filters.teamId
  );
}

const TEXT_BUTTON = cn(
  PRESSED_CLASS,
  'rounded-(--fx-r-m) px-2 py-1 text-sm font-semibold text-(--fx-link) transition-[translate] duration-(--fx-t-hover) ease-(--fx-ease-out) hover:-translate-y-px',
);

function ThreadRow({
  thread: t,
  selected,
  onSelect,
}: {
  thread: ConversationThread;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const {
    icon: ChannelIcon,
    accentClassName,
    label: channelLabel,
  } = channelCapabilities(t.channelType);
  const unread = t.unreadCount > 0;
  return (
    <button
      type="button"
      onClick={() => onSelect(t.id)}
      aria-current={selected ? 'true' : undefined}
      aria-label={[
        t.name,
        unread ? `${t.unreadCount} unread` : null,
        t.lastMessagePreview,
      ]
        .filter(Boolean)
        .join(', ')}
      className={cn(
        PRESSED_CLASS,
        'relative flex w-full items-start gap-3 border-b border-(--fx-line) p-3 text-start transition-[translate,box-shadow,background-color] duration-(--fx-t-hover) ease-(--fx-ease-out)',
        'hover:z-1 hover:-translate-y-px hover:bg-(--fx-surface) hover:shadow-[0_4px_10px_var(--fx-shade)] motion-reduce:hover:translate-y-0',
        selected && 'bg-(--fx-link-bg) hover:bg-(--fx-link-bg)',
      )}
      data-testid={`thread-row-${t.id}`}
      data-fx-thread-row=""
    >
      <span className="relative mt-0.5 shrink-0">
        <Avatar className="size-9">
          <AvatarFallback>{initials(t.name)}</AvatarFallback>
        </Avatar>
        <span
          className={cn(
            'absolute -end-1 -bottom-1 flex size-4 items-center justify-center rounded-full ring-2 ring-(--fx-surface)',
            accentClassName,
          )}
          title={channelLabel}
        >
          <ChannelIcon className="size-2.5" aria-hidden="true" />
        </span>
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-center justify-between gap-2">
          <span
            className={cn(
              'truncate text-sm text-(--fx-ink)',
              unread ? 'font-bold' : 'font-semibold',
            )}
          >
            {t.name}
          </span>
          <FxMoment
            iso={t.lastMessageAt}
            className={cn(
              'shrink-0 text-xs',
              unread ? 'font-semibold text-(--fx-link)' : 'text-(--fx-ink-3)',
            )}
          />
        </span>
        <span className="flex items-center justify-between gap-2">
          <span className="truncate text-sm text-(--fx-ink-2)">
            {t.lastMessagePreview}
          </span>
          {unread && (
            <span
              className="inline-grid h-5 min-w-5 shrink-0 place-items-center rounded-(--fx-r-pill) bg-(--fx-link) px-1.5 text-xs font-semibold tabular-nums text-(--fx-surface)"
              data-testid="unread-badge"
              aria-label={`${t.unreadCount} unread`}
            >
              {t.unreadCount}
            </span>
          )}
        </span>
        <span className="mt-1 flex flex-wrap items-center gap-1">
          <StatusBadge
            status={t.status}
            registry={THREAD_STATUS_REGISTRY}
            size="sm"
          />
          <StatusBadge
            status={t.priority}
            registry={THREAD_PRIORITY_REGISTRY}
            size="sm"
          />
          {t.lifecycle && (
            <StatusBadge
              status={t.lifecycle.key}
              registry={
                {
                  [t.lifecycle.key]: {
                    label: t.lifecycle.label,
                    tone: 'secondary',
                    hex: t.lifecycle.color ?? undefined,
                  },
                } as StatusRegistry<string>
              }
              size="sm"
            />
          )}
          {t.tags.slice(0, 1).map((tag) => (
            <Badge
              key={tag.id}
              variant="secondary"
              appearance="light"
              size="sm"
            >
              {tag.emoji && <span aria-hidden>{tag.emoji}</span>}
              {tag.name}
            </Badge>
          ))}
          {t.tags.length > 1 && (
            <Badge
              variant="secondary"
              appearance="light"
              size="sm"
              title={t.tags
                .slice(1)
                .map((g) => g.name)
                .join(', ')}
            >
              +{t.tags.length - 1}
            </Badge>
          )}
          <span className="ms-auto truncate text-xs text-(--fx-ink-3)">
            {t.assignedUserName ?? 'Unassigned'}
          </span>
        </span>
      </span>
    </button>
  );
}

export function FxThreadList({
  threads,
  isLoading,
  error,
  filters,
  setFilters,
  selectedId,
  onSelect,
  onRetry,
  onClearFilters,
}: ThreadListProps) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const [pointerOn, setPointerOn] = useState(false);
  const [scrolledDown, setScrolledDown] = useState(false);
  const holding = pointerOn || scrolledDown;
  const { rows, waiting, release } = useHeldThreads(
    threads,
    holding,
    JSON.stringify(filters),
  );
  const filtered = fxInboxFiltered(filters);

  const showLatest = () => {
    release();
    scrollerRef.current?.scrollTo({ top: 0 });
  };

  let body: ReactNode;
  if (isLoading && threads.length === 0) {
    body = (
      <div
        className="space-y-2 p-3"
        aria-busy="true"
        data-testid="thread-list-loading"
      >
        <Skeleton className="h-16 w-full rounded-(--fx-r-m)" />
        <Skeleton className="h-16 w-full rounded-(--fx-r-m)" />
        <Skeleton className="h-16 w-full rounded-(--fx-r-m)" />
      </div>
    );
  } else if (error) {
    body = (
      <div
        className="flex flex-col items-center gap-2 px-4 py-10 text-center animate-in fade-in-0 duration-(--fx-t-hover) motion-reduce:animate-none"
        data-testid="thread-list-error"
      >
        <TriangleAlert
          className="size-6 text-(--fx-ink-3)"
          aria-hidden="true"
        />
        <p className="text-sm text-(--fx-ink)">
          Couldn&apos;t load the conversations.
        </p>
        {onRetry && (
          <button type="button" onClick={onRetry} className={TEXT_BUTTON}>
            Try again
          </button>
        )}
      </div>
    );
  } else if (rows.length === 0) {
    body = (
      <div
        className="flex flex-col items-center gap-2 px-4 py-10 text-center animate-in fade-in-0 duration-(--fx-t-hover) motion-reduce:animate-none"
        data-testid="thread-list-empty"
      >
        <MessagesSquare
          className="size-6 text-(--fx-ink-3)"
          aria-hidden="true"
        />
        {filtered ? (
          <>
            <p className="text-sm text-(--fx-ink)">
              No conversations match these filters.
            </p>
            {onClearFilters && (
              <button
                type="button"
                onClick={onClearFilters}
                className={TEXT_BUTTON}
                data-testid="thread-list-clear"
              >
                Clear filters
              </button>
            )}
          </>
        ) : (
          <p className="text-sm text-(--fx-ink)">
            Conversations show here when contacts message you.
          </p>
        )}
      </div>
    );
  } else {
    body = (
      <ul aria-label="Conversations">
        {rows.map((t) => (
          <li key={t.id}>
            <ThreadRow
              thread={t}
              selected={selectedId === t.id}
              onSelect={onSelect}
            />
          </li>
        ))}
      </ul>
    );
  }

  return (
    <div
      className="flex h-full flex-col"
      data-testid="thread-list"
      data-fx-thread-list=""
    >
      <div className="border-b border-(--fx-line) p-2.5">
        <div className="relative">
          <Search
            className="pointer-events-none absolute start-2.5 top-1/2 z-1 size-4 -translate-y-1/2 text-(--fx-ink-3)"
            aria-hidden="true"
          />
          <Input
            className="ps-8"
            placeholder="Search conversations"
            aria-label="Search conversations"
            value={filters.search}
            onChange={(e) => setFilters({ search: e.target.value })}
            data-testid="thread-search"
          />
        </div>
      </div>

      <div
        ref={scrollerRef}
        className="relative min-h-0 flex-1 overflow-y-auto"
        onPointerEnter={(e) => {
          // A finger never holds the list (its leave fires as it lifts);
          // scrolling down does.
          if (e.pointerType !== 'touch') setPointerOn(true);
        }}
        onPointerLeave={() => setPointerOn(false)}
        onScroll={(e) => setScrolledDown(e.currentTarget.scrollTop > 0)}
        data-testid="thread-list-scroller"
      >
        {waiting > 0 && (
          <div className="pointer-events-none sticky top-2 z-2 flex h-0 justify-center">
            <button
              type="button"
              onClick={showLatest}
              className={cn(
                PRESSED_CLASS,
                'pointer-events-auto inline-flex min-h-8 items-center gap-1.5 rounded-(--fx-r-pill) bg-(--fx-link) px-3 text-sm font-semibold text-(--fx-surface) shadow-[0_6px_18px_var(--fx-shade)] transition-[translate,scale] duration-(--fx-t-hover) ease-(--fx-ease-out) animate-in fade-in-0 slide-in-from-top-1 hover:-translate-y-0.5 active:scale-[0.97] motion-reduce:animate-none motion-reduce:hover:translate-y-0',
              )}
              data-testid="thread-list-new-pill"
              data-fx-new-rows=""
            >
              <ArrowUp className="size-4" aria-hidden="true" />
              {waiting} new
            </button>
          </div>
        )}
        {body}
      </div>
    </div>
  );
}
