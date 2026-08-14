'use client';

/**
 * <ConversationDrawer> - the reusable chat panel (plan 05 §6). Self-contained:
 * gets everything through useMessages + conversation-service, so it can later
 * dock into CRM forms unchanged. Header (contact, assign, lifecycle,
 * Messages | Activities tabs) + thread window + CSW-aware composer.
 */
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Inbox,
  Search,
  UserPlus,
  X,
} from 'lucide-react';

import { StatusBadge } from '@/components/platform/status-badge';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useMessages } from '@/hooks/use-messages';
import { conversationService } from '@/services/conversation-service';
import { workspaceService } from '@/services/workspace-service';
import type {
  ConversationMessage,
  QuickReply,
  WhatsAppTemplate,
  WorkspaceMember,
} from '@/types/omnichannel';

import { Composer } from './composer';
import { useDatetime } from '@/hooks/use-datetime';
import { dateKey, parseUtc } from '@/lib/datetime';
import { MessageBubble } from './message-bubble';
import { THREAD_PRIORITY_REGISTRY, THREAD_STATUS_REGISTRY } from './thread-status';

export interface ConversationDrawerProps {
  contactId: string | null;
  /** Empty-state copy when no thread is selected. */
  emptyHint?: string;
  /**
   * Messages-only chrome: hide the header (contact identity, Messages/Activities
   * tabs, in-thread search, assign + lifecycle controls) and render just the
   * scrollable thread + composer. Used by the embed thread widget so it drops
   * into a narrow lead-page side panel. Default false (full drawer).
   */
  compact?: boolean;
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('');
}

/** Human day label in the viewer's tz: Today / Yesterday / 4 June 2026.
 * Backend timestamps are naive-UTC by convention - `dateKey` pins the parse
 * to UTC and resolves the calendar day in the given tz (plan sprint-2/05). */
export function dayLabel(
  iso: string,
  now: Date = new Date(),
  timeZone?: string | null,
): string {
  const key = dateKey(iso, { timeZone });
  if (key === dateKey(now, { timeZone })) return 'Today';
  const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  if (key === dateKey(yesterday, { timeZone })) return 'Yesterday';
  const d = parseUtc(iso);
  if (!d) return '-';
  try {
    return new Intl.DateTimeFormat(undefined, {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      timeZone: timeZone ?? undefined,
    }).format(d);
  } catch {
    return new Intl.DateTimeFormat(undefined, {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    }).format(d);
  }
}

export function ConversationDrawer({ contactId, emptyHint = 'Select a conversation', compact = false }: ConversationDrawerProps) {
  const {
    thread,
    messages,
    isLoading,
    error,
    isSending,
    sendError,
    send,
    sendTemplate,
    sendMedia,
    sendInteractive,
    sendLocation,
    sendContacts,
    react,
    addNote,
    assign,
    assignToMe,
    setStatus,
  } = useMessages(contactId);

  const { timeZone, formatTime } = useDatetime();
  const [tab, setTab] = useState<'messages' | 'activities'>('messages');
  const [templates, setTemplates] = useState<WhatsAppTemplate[]>([]);
  const [quickReplies, setQuickReplies] = useState<QuickReply[]>([]);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [replyTo, setReplyTo] = useState<ConversationMessage | null>(null);

  // In-thread search (WhatsApp chat search): term + active-match cursor.
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [matchCursor, setMatchCursor] = useState(0); // 0 = newest match

  // Deep link: ?msg=<id> (the bubble menu's "Copy link to message") - scroll to
  // + briefly highlight that message once its thread is loaded.
  const [focusMsgId, setFocusMsgId] = useState<string | null>(null);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('thread') === contactId) setFocusMsgId(params.get('msg'));
    else setFocusMsgId(null);
  }, [contactId]);

  // Switching threads drops any in-progress reply + search.
  useEffect(() => {
    setReplyTo(null);
    setSearchOpen(false);
    setSearchTerm('');
    setMatchCursor(0);
  }, [contactId]);

  // CSW lock is a clock comparison - re-evaluate periodically while open.
  const [nowTick, setNowTick] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNowTick(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);
  const windowOpen = useMemo(
    () => !!thread?.cswExpiresAt && Date.parse(thread.cswExpiresAt) > nowTick,
    [thread?.cswExpiresAt, nowTick],
  );

  useEffect(() => {
    if (!thread?.channelId) return setTemplates([]);
    conversationService.listTemplates(thread.channelId).then(setTemplates).catch(() => setTemplates([]));
  }, [thread?.channelId]);

  useEffect(() => {
    if (!thread?.workspaceId) return;
    conversationService.listQuickReplies(thread.workspaceId).then(setQuickReplies).catch(() => setQuickReplies([]));
    workspaceService.getMembers(thread.workspaceId).then(setMembers).catch(() => setMembers([]));
  }, [thread?.workspaceId]);

  // Pin the thread to the latest message.
  const bottomRef = useRef<HTMLDivElement>(null);
  const visibleMessages = useMemo(
    () => (tab === 'activities' ? messages.filter((m) => m.senderType === 'SYSTEM') : messages),
    [messages, tab],
  );

  // In-thread search matches (newest → oldest, like WhatsApp's ↑ navigation).
  const activeSearch = searchOpen ? searchTerm.trim().toLowerCase() : '';
  const matchIds = useMemo(() => {
    if (!activeSearch) return [];
    return visibleMessages
      .filter((m) => (m.body ?? '').toLowerCase().includes(activeSearch))
      .map((m) => m.id)
      .reverse();
  }, [visibleMessages, activeSearch]);
  const activeMatchId = matchIds[Math.min(matchCursor, Math.max(matchIds.length - 1, 0))] ?? null;
  useEffect(() => setMatchCursor(0), [activeSearch]);

  const stepMatch = useCallback(
    (delta: number) => {
      if (!matchIds.length) return;
      setMatchCursor((c) => (c + delta + matchIds.length) % matchIds.length);
    },
    [matchIds.length],
  );

  const messageRefs = useRef(new Map<string, HTMLDivElement>());
  useEffect(() => {
    if (activeMatchId) {
      messageRefs.current.get(activeMatchId)?.scrollIntoView({ block: 'center' });
    }
  }, [activeMatchId]);

  // Once the deep-linked message is in view, scroll to it; drop the focus after a
  // beat so new-message auto-scroll resumes (highlight rides `isActiveMatch`).
  useEffect(() => {
    if (!focusMsgId) return;
    const el = messageRefs.current.get(focusMsgId);
    if (!el) return;
    el.scrollIntoView({ block: 'center' });
    const t = setTimeout(() => setFocusMsgId(null), 2500);
    return () => clearTimeout(t);
  }, [focusMsgId, visibleMessages.length]);

  useEffect(() => {
    // Don't yank the view to the bottom while jumping matches or focusing a deep link.
    if (activeSearch || focusMsgId) return;
    bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [visibleMessages.length, contactId, activeSearch, focusMsgId]);

  const closeSearch = useCallback(() => {
    setSearchOpen(false);
    setSearchTerm('');
    setMatchCursor(0);
  }, []);

  if (!contactId) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground" data-testid="drawer-empty">
        <Inbox className="size-8" />
        <p className="text-sm">{emptyHint}</p>
      </div>
    );
  }

  if (isLoading || !thread) {
    return (
      <div className="flex h-full flex-col gap-3 p-4" data-testid="drawer-loading">
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : (
          <>
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-20 w-2/3" />
            <Skeleton className="h-20 w-2/3 self-end" />
            <Skeleton className="h-20 w-1/2" />
          </>
        )}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col" data-testid="conversation-drawer">
      {/* Header - hidden in compact (messages-only) mode. */}
      {!compact && (
      <div className="flex flex-wrap items-center gap-3 border-b px-4 py-3">
        <Avatar className="size-9">
          <AvatarFallback>{initials(thread.name)}</AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="truncate font-medium" data-testid="drawer-contact-name">
              {thread.name}
            </span>
            <Badge variant="secondary" appearance="light" size="sm">
              WhatsApp
            </Badge>
          </div>
          <div className="text-xs text-muted-foreground">{thread.phone}</div>
        </div>

        <div className="ms-auto flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Search in conversation"
            onClick={() => (searchOpen ? closeSearch() : setSearchOpen(true))}
            data-testid="thread-search-toggle"
          >
            <Search className="size-4" />
          </Button>
          <StatusBadge status={thread.priority} registry={THREAD_PRIORITY_REGISTRY} size="sm" />
          <StatusBadge status={thread.status} registry={THREAD_STATUS_REGISTRY} size="sm" />

          {/* Assign / reassign */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" data-testid="assign-trigger">
                <UserPlus className="size-4" />
                {thread.assignedUserName ?? 'Unassigned'}
                <ChevronDown className="size-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel>Assign to</DropdownMenuLabel>
              <DropdownMenuItem onClick={() => void assignToMe()} data-testid="assign-me">
                Assign to me
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              {members.map((m) => (
                <DropdownMenuItem key={m.userId} onClick={() => void assign(m.userId)}>
                  {m.name ?? m.email}
                </DropdownMenuItem>
              ))}
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => void assign(null)} data-testid="assign-clear">
                Unassign
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Lifecycle */}
          {thread.status !== 'SNOOZED' && thread.status !== 'CLOSED' ? (
            <>
              <Button variant="outline" size="sm" onClick={() => void setStatus('SNOOZED')} data-testid="thread-snooze">
                <Clock className="size-4" /> Snooze
              </Button>
              <Button variant="outline" size="sm" onClick={() => void setStatus('CLOSED')} data-testid="thread-close">
                <CheckCircle2 className="size-4" /> Close
              </Button>
            </>
          ) : (
            <Button variant="outline" size="sm" onClick={() => void setStatus('OPEN')} data-testid="thread-reopen">
              Reopen
            </Button>
          )}
        </div>

        <Tabs value={tab} onValueChange={(v) => setTab(v as 'messages' | 'activities')} className="w-full">
          <TabsList>
            <TabsTrigger value="messages" data-testid="tab-messages">
              Messages
            </TabsTrigger>
            <TabsTrigger value="activities" data-testid="tab-activities">
              Activities
            </TabsTrigger>
          </TabsList>
        </Tabs>

        {searchOpen && (
          <div className="flex w-full items-center gap-2" data-testid="thread-search-bar">
            <Input
              autoFocus
              placeholder="Search in this conversation…"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') stepMatch(e.shiftKey ? -1 : 1);
                if (e.key === 'Escape') closeSearch();
              }}
              className="h-8 flex-1"
              data-testid="thread-search-input"
            />
            <span className="shrink-0 text-xs tabular-nums text-muted-foreground" data-testid="thread-search-count">
              {activeSearch ? `${matchIds.length ? matchCursor + 1 : 0} / ${matchIds.length}` : ''}
            </span>
            {/* ↑ = older match, ↓ = newer (matches are newest-first). */}
            <Button variant="outline" size="icon" className="size-8" aria-label="Older match" disabled={!matchIds.length} onClick={() => stepMatch(1)} data-testid="thread-search-prev">
              <ChevronUp className="size-4" />
            </Button>
            <Button variant="outline" size="icon" className="size-8" aria-label="Newer match" disabled={!matchIds.length} onClick={() => stepMatch(-1)} data-testid="thread-search-next">
              <ChevronDown className="size-4" />
            </Button>
            <Button variant="ghost" size="icon" className="size-8" aria-label="Close search" onClick={closeSearch} data-testid="thread-search-close">
              <X className="size-4" />
            </Button>
          </div>
        )}
      </div>
      )}

      {/* Thread */}
      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-2.5 p-4" data-testid="thread-window">
          {visibleMessages.length === 0 && (
            <p className="py-8 text-center text-sm text-muted-foreground">
              {tab === 'activities' ? 'No internal notes yet.' : 'No messages yet.'}
            </p>
          )}
          {visibleMessages.map((m, i) => (
            <Fragment key={m.id}>
              {/* Day separator pill whenever the calendar day changes. */}
              {(i === 0 ||
                dateKey(visibleMessages[i - 1].createdAt, { timeZone }) !==
                  dateKey(m.createdAt, { timeZone })) && (
                <div className="flex justify-center py-1">
                  <span
                    className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground shadow-xs"
                    data-testid="day-pill"
                  >
                    {dayLabel(m.createdAt, new Date(), timeZone)}
                  </span>
                </div>
              )}
              <div
                ref={(el) => {
                  if (el) messageRefs.current.set(m.id, el);
                  else messageRefs.current.delete(m.id);
                }}
              >
                <MessageBubble
                  message={m}
                  contactName={thread.name}
                  formatTime={formatTime}
                  highlight={activeSearch || undefined}
                  isActiveMatch={m.id === activeMatchId || m.id === focusMsgId}
                  onReply={
                    tab === 'messages'
                      ? (msg) => {
                          setReplyTo(msg);
                        }
                      : undefined
                  }
                  onReact={
                    tab === 'messages' && m.senderType !== 'SYSTEM' && windowOpen
                      ? (msg, emoji) => void react(msg.id, emoji)
                      : undefined
                  }
                />
              </div>
            </Fragment>
          ))}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      {/* Composer - note mode on the Activities tab */}
      <Composer
        windowOpen={windowOpen}
        templates={templates}
        quickReplies={quickReplies}
        isSending={isSending}
        sendError={sendError}
        onSend={send}
        onSendTemplate={sendTemplate}
        onSendMedia={sendMedia}
        onSendInteractive={sendInteractive}
        onSendLocation={sendLocation}
        onSendContacts={sendContacts}
        mode={tab === 'activities' ? 'note' : 'message'}
        onAddNote={addNote}
        replyTo={replyTo}
        onCancelReply={() => setReplyTo(null)}
      />
    </div>
  );
}
