'use client';

/**
 * The conversation pane under the Foundryx UIUX switch (W1-CONV). Same data,
 * same requests and the same steps as today's pane (`useConversationPane` is
 * shared); what changes is the look plus these playbook behaviours:
 *
 * - One red action: "Close conversation" (full label "Close Lim Wei Jie's
 *   conversation"), or "Reopen conversation" once snoozed or closed. It sits
 *   in the pane's header, or, when the host page draws a page header
 *   (`fxPageHeader`), it is handed to that header through
 *   `useRegisterMainAction` so it never shows twice.
 * - Assign, Snooze, Search in conversation and Contact panel are icon actions.
 * - Done toasts say what, for whom and by whom; Undo only where the existing
 *   API can put things back exactly: assign (puts the previous owner and team
 *   back), snooze (back to open), close (reopens), reopen from snoozed (snoozes
 *   again). Reopening a closed conversation has no Undo: closing needs a
 *   reason, so it cannot be put back by one click.
 * - Agent bubbles say their delivery state (in the bubble).
 * - Scrolled up, new messages never pull the view down; a "New messages" pill
 *   at the bottom edge jumps there instead (gap audit 15).
 * - The 24-hour window strip and the kept draft live in the composer.
 */
import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  ArrowDown,
  ChevronDown,
  ChevronUp,
  Clock,
  Inbox,
  PanelRight,
  X,
} from 'lucide-react';
import { useSession } from 'next-auth/react';
import type { ThreadStatus } from '@/types/omnichannel';
import { ApiError } from '@/lib/api-client';
import { dateKey } from '@/lib/datetime';
import { useReducedMotion } from '@/lib/motion';
import { toast } from '@/lib/toast';
import { cn } from '@/lib/utils';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { FxIconActionButton } from '@/components/fx/actions/icon-action';
import { FxMainAction } from '@/components/fx/actions/main-action';
import {
  useHideMainAction,
  useRegisterMainAction,
  type FxMainActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { FxDayLine } from '@/components/fx/fields/fx-moment';
import { FxTooltip } from '@/components/fx/fx-tooltip';
import { StatusBadge } from '@/components/platform/status-badge';
import { ActivityFeed } from '../activity-feed';
import { CloseThreadDialog } from '../close-thread-dialog';
import { Composer } from '../composer';
import { ContactPanel } from '../contact-panel';
import type { ConversationDrawerProps } from '../conversation-drawer';
import { MessageBubble } from '../message-bubble';
import { ShortcutMenu } from '../shortcut-menu';
import {
  THREAD_PRIORITY_REGISTRY,
  THREAD_STATUS_REGISTRY,
} from '../thread-status';
import { useConversationPane } from '../use-conversation-pane';
import { fxConversationOf } from './fx-close-thread-dialog';

/** Within this many px of the bottom counts as "reading the newest". */
const AT_BOTTOM_PX = 48;

function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('');
}

function errorText(e: unknown, fallback: string): string {
  return e instanceof ApiError || e instanceof Error
    ? e.message || fallback
    : fallback;
}

/** The red action for a thread in `status` (pure, tested). */
export function fxPaneMainAction(
  status: ThreadStatus,
  name: string,
  handlers: { close: () => void; reopen: () => void },
  working = false,
): FxMainActionSpec {
  const subject = fxConversationOf(name);
  return status === 'OPEN'
    ? {
        id: 'conversation-close',
        label: 'Close conversation',
        fullLabel: `Close ${subject}`,
        onClick: handlers.close,
      }
    : {
        id: 'conversation-reopen',
        label: 'Reopen conversation',
        fullLabel: `Reopen ${subject}`,
        onClick: handlers.reopen,
        working,
      };
}

export function FxConversationDrawer({
  contactId,
  emptyHint = 'Select a conversation',
  compact = false,
  fxPageHeader = false,
}: ConversationDrawerProps) {
  const pane = useConversationPane(contactId);
  const {
    thread,
    isLoading,
    error,
    erased,
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
    assignTeam,
    setStatus,
    closeThread,
    patchContact,
    moveLifecycle,
    messages,
    events,
    reloadEvents,
    closeReasons,
    closeDialogOpen,
    setCloseDialogOpen,
    timeZone,
    formatTime,
    tab,
    setTab,
    templates,
    quickReplies,
    members,
    replyTo,
    setReplyTo,
    teams,
    contactPanelOpen,
    isDesktopPanel,
    setPanelOpen,
    toggleContactPanel,
    searchOpen,
    setSearchOpen,
    searchTerm,
    setSearchTerm,
    matchCursor,
    focusMsgId,
    capabilities,
    hasActiveChannel,
    windowOpen,
    humanAgentWindowOpen,
    visitorPresence,
    visibleMessages,
    activeSearch,
    matchIds,
    activeMatchId,
    stepMatch,
    messageRefs,
    closeSearch,
  } = pane;

  const { data: session } = useSession();
  const me = session?.user?.name ?? undefined;
  const reduced = useReducedMotion();
  const name = thread?.name ?? '';

  // ── Done toasts with Undo where the API can put it back ─────────────────
  const owner = useMemo(
    () => ({
      userId: thread?.assignedUserId ?? null,
      teamId: thread?.assignedTeamId ?? null,
    }),
    [thread?.assignedUserId, thread?.assignedTeamId],
  );

  const undoOwner = useCallback(
    (prev: { userId: string | null; teamId: string | null }) => () => {
      patchContact({ assignedTeamId: prev.teamId, assignedUserId: prev.userId })
        .then(() => reloadEvents())
        .catch((e: unknown) =>
          toast.error(errorText(e, 'Could not undo the assignment.')),
        );
    },
    [patchContact, reloadEvents],
  );

  const runAssign = useCallback(
    (action: () => Promise<void>, what: string) => {
      const prev = owner;
      action()
        .then(() => {
          toast.fxDone({ what, byWhom: me, undo: undoOwner(prev) });
        })
        .catch((e: unknown) =>
          toast.error(errorText(e, 'Could not update the assignment.')),
        );
    },
    [owner, me, undoOwner],
  );

  const snooze = useCallback(() => {
    setStatus('SNOOZED')
      .then(() =>
        toast.fxDone({
          what: `${fxConversationOf(name)} snoozed`.replace(/^./, (c) =>
            c.toUpperCase(),
          ),
          byWhom: me,
          undo: () => {
            setStatus('OPEN').catch((e: unknown) =>
              toast.error(errorText(e, 'Could not undo the snooze.')),
            );
          },
        }),
      )
      .catch((e: unknown) =>
        toast.error(errorText(e, 'Could not snooze this conversation.')),
      );
  }, [setStatus, name, me]);

  const [reopening, setReopening] = useState(false);
  const reopen = useCallback(async () => {
    const from = thread?.status;
    setReopening(true);
    try {
      await setStatus('OPEN');
      await reloadEvents();
      toast.fxDone({
        what: `${fxConversationOf(name)} reopened`.replace(/^./, (c) =>
          c.toUpperCase(),
        ),
        byWhom: me,
        // Back to snoozed is one PATCH; back to closed needs a close reason.
        undo:
          from === 'SNOOZED'
            ? () => {
                setStatus('SNOOZED').catch((e: unknown) =>
                  toast.error(errorText(e, 'Could not undo the reopen.')),
                );
              }
            : undefined,
      });
    } catch (e) {
      toast.error(
        e instanceof ApiError
          ? e.message
          : 'Could not reopen this conversation.',
      );
    } finally {
      setReopening(false);
    }
  }, [thread?.status, setStatus, reloadEvents, name, me]);

  const onCloseConfirmed = useCallback(
    async (closeReasonId: string, note: string) => {
      await closeThread({ closeReasonId, note: note || undefined });
      await reloadEvents();
      const reason = closeReasons.find((r) => r.id === closeReasonId)?.name;
      toast.fxDone({
        what: `${fxConversationOf(name)} closed${reason ? ` as ${reason}` : ''}`.replace(
          /^./,
          (c) => c.toUpperCase(),
        ),
        byWhom: me,
        undo: () => {
          setStatus('OPEN')
            .then(() => reloadEvents())
            .catch((e: unknown) =>
              toast.error(errorText(e, 'Could not undo the close.')),
            );
        },
      });
    },
    [closeThread, reloadEvents, closeReasons, name, me, setStatus],
  );

  // ── The one red action ───────────────────────────────────────────────────
  const openClose = useCallback(
    () => setCloseDialogOpen(true),
    [setCloseDialogOpen],
  );
  const reopenClick = useCallback(() => void reopen(), [reopen]);
  const mainAction = useMemo(
    () =>
      thread && !compact
        ? fxPaneMainAction(
            thread.status,
            thread.name,
            { close: openClose, reopen: reopenClick },
            reopening,
          )
        : null,
    [thread, compact, openClose, reopenClick, reopening],
  );
  useRegisterMainAction(fxPageHeader ? mainAction : null);
  useHideMainAction(closeDialogOpen);

  // ── Scrolling: never pull a reader down; offer a pill instead ───────────
  const scrollerRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);
  const [newBelow, setNewBelow] = useState(false);
  const seen = useRef<{
    contactId: string | null;
    count: number;
    tab: string;
  }>({
    contactId: null,
    count: 0,
    tab,
  });

  const toBottom = useCallback(
    (smooth: boolean) => {
      const el = scrollerRef.current;
      if (!el) return;
      if (typeof el.scrollTo === 'function') {
        el.scrollTo({
          top: el.scrollHeight,
          behavior: smooth && !reduced ? 'smooth' : 'auto',
        });
      } else {
        el.scrollTop = el.scrollHeight;
      }
      atBottomRef.current = true;
      setNewBelow(false);
    },
    [reduced],
  );

  const onScroll = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const atBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight <= AT_BOTTOM_PX;
    atBottomRef.current = atBottom;
    if (atBottom) setNewBelow(false);
  }, []);

  useEffect(() => {
    const count = visibleMessages.length;
    const before = seen.current;
    seen.current = { contactId, count, tab };
    // Jumping between search matches or to a linked message owns the scroll.
    if (activeSearch || focusMsgId) return;
    // A new thread, or coming back from Activities: start at the newest.
    if (before.contactId !== contactId || before.tab !== tab) {
      atBottomRef.current = true;
      setNewBelow(false);
      toBottom(false);
      return;
    }
    if (count <= before.count) return;
    const last = visibleMessages[count - 1];
    const own = last?.senderType === 'AGENT' && last.id.startsWith('temp-');
    if (atBottomRef.current || own || before.count === 0) toBottom(false);
    else setNewBelow(true);
  }, [visibleMessages, contactId, tab, activeSearch, focusMsgId, toBottom]);

  // ── States before a thread shows ─────────────────────────────────────────
  if (!contactId || erased) {
    return (
      <div
        className="flex h-full flex-col items-center justify-center gap-2 text-(--fx-ink-3)"
        data-testid="drawer-empty"
      >
        <Inbox className="size-8" aria-hidden="true" />
        <p className="text-sm">{emptyHint}</p>
      </div>
    );
  }

  if (isLoading || !thread) {
    return (
      <div
        className="flex h-full flex-col gap-3 p-4"
        data-testid="drawer-loading"
      >
        {error ? (
          <p role="alert" className="text-sm text-(--fx-act)">
            {error}
          </p>
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

  const assignee = thread.assignedTeamId
    ? `${thread.assignedTeamName ?? 'Team'} · ${thread.assignedUserName ?? 'Unassigned'}`
    : (thread.assignedUserName ?? null);
  const canSnooze = thread.status !== 'SNOOZED' && thread.status !== 'CLOSED';

  return (
    <div
      className="flex h-full flex-col bg-(--fx-surface)"
      data-testid="conversation-drawer"
      data-fx-pane=""
    >
      {!compact && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-(--fx-line) px-4 py-3">
          <Avatar className="size-10">
            <AvatarFallback>{initials(thread.name)}</AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1 basis-40">
            <div className="flex flex-wrap items-center gap-1.5">
              <span
                className="truncate font-semibold text-(--fx-ink)"
                data-testid="drawer-contact-name"
              >
                {thread.name}
              </span>
              <Badge variant="secondary" appearance="light" size="sm">
                <capabilities.icon className="size-3" />
                {capabilities.label}
              </Badge>
              <StatusBadge
                status={thread.priority}
                registry={THREAD_PRIORITY_REGISTRY}
                size="sm"
              />
              <StatusBadge
                status={thread.status}
                registry={THREAD_STATUS_REGISTRY}
                size="sm"
              />
            </div>
            <div className="truncate text-xs text-(--fx-ink-3)">
              <span className="tabular-nums">{thread.phone}</span>
              <span data-testid="assign-team-label">
                {thread.phone ? ' · ' : ''}
                {assignee ? `Assigned to ${assignee}` : 'Unassigned'}
              </span>
            </div>
          </div>

          <div
            className="ms-auto flex flex-wrap items-center justify-end gap-1.5"
            data-fx-pane-actions=""
          >
            <DropdownMenu>
              <FxTooltip label="Assign">
                <DropdownMenuTrigger asChild>
                  <FxIconActionButton
                    label="Assign"
                    icon="assign"
                    data-testid="assign-trigger"
                  />
                </DropdownMenuTrigger>
              </FxTooltip>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel>Assign to</DropdownMenuLabel>
                <DropdownMenuItem
                  onClick={() =>
                    runAssign(
                      assignToMe,
                      `${thread.name} assigned to ${me ?? 'you'}`,
                    )
                  }
                  data-testid="assign-me"
                >
                  Assign to me
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                {members.map((m) => (
                  <DropdownMenuItem
                    key={m.userId}
                    onClick={() =>
                      runAssign(
                        () => assign(m.userId),
                        `${thread.name} assigned to ${m.name ?? m.email}`,
                      )
                    }
                  >
                    {m.name ?? m.email}
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() =>
                    runAssign(() => assign(null), `${thread.name} unassigned`)
                  }
                  data-testid="assign-clear"
                >
                  Unassign
                </DropdownMenuItem>
                {teams.length > 0 && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuLabel>Teams</DropdownMenuLabel>
                    {teams.map((t) => (
                      <DropdownMenuItem
                        key={t.id}
                        onClick={() =>
                          runAssign(
                            () => assignTeam(t.id),
                            `${thread.name} assigned to ${t.name}`,
                          )
                        }
                        data-testid={`assign-team-${t.id}`}
                      >
                        {t.name}
                      </DropdownMenuItem>
                    ))}
                    {thread.assignedTeamId && (
                      <DropdownMenuItem
                        onClick={() =>
                          runAssign(
                            () => assignTeam(null),
                            `${thread.name} removed from ${thread.assignedTeamName ?? 'the team'}`,
                          )
                        }
                        data-testid="assign-team-clear"
                      >
                        Clear team
                      </DropdownMenuItem>
                    )}
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>

            {canSnooze && (
              <FxTooltip label="Snooze">
                <FxIconActionButton
                  label="Snooze"
                  icon="reminder"
                  iconNode={<Clock className="size-[18px]" />}
                  onClick={snooze}
                  data-testid="thread-snooze"
                />
              </FxTooltip>
            )}

            {tab === 'messages' && (
              <FxTooltip label="Search in conversation">
                <FxIconActionButton
                  label="Search in conversation"
                  icon="search"
                  aria-pressed={searchOpen}
                  onClick={() =>
                    searchOpen ? closeSearch() : setSearchOpen(true)
                  }
                  className={cn(
                    searchOpen && 'border-(--fx-link) text-(--fx-link)',
                  )}
                  data-testid="thread-search-toggle"
                />
              </FxTooltip>
            )}

            <FxTooltip label="Contact panel">
              <FxIconActionButton
                label="Contact panel"
                icon="columns"
                iconNode={<PanelRight className="size-[18px]" />}
                aria-pressed={contactPanelOpen}
                onClick={toggleContactPanel}
                className={cn(
                  contactPanelOpen && 'border-(--fx-link) text-(--fx-link)',
                )}
                data-testid="contact-panel-toggle"
              />
            </FxTooltip>

            <ShortcutMenu contactId={contactId} />

            {!fxPageHeader && mainAction && (
              <span
                data-testid={
                  thread.status === 'OPEN' ? 'thread-close' : 'thread-reopen'
                }
                className="contents"
              >
                <FxMainAction
                  key={mainAction.id}
                  label={mainAction.label}
                  fullLabel={mainAction.fullLabel}
                  onClick={mainAction.onClick}
                  working={mainAction.working}
                />
              </span>
            )}
          </div>

          <Tabs
            value={tab}
            onValueChange={(v) => {
              setTab(v as 'messages' | 'activities');
              if (v === 'activities') closeSearch();
            }}
            className="w-full"
          >
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
            <div
              className="flex w-full items-center gap-1.5"
              data-testid="thread-search-bar"
            >
              <Input
                autoFocus
                placeholder="Search in this conversation"
                aria-label="Search in this conversation"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') stepMatch(e.shiftKey ? -1 : 1);
                  if (e.key === 'Escape') closeSearch();
                }}
                className="h-9 min-w-0 flex-1"
                data-testid="thread-search-input"
              />
              <span
                className="shrink-0 text-xs tabular-nums text-(--fx-ink-3)"
                data-testid="thread-search-count"
              >
                {activeSearch
                  ? `${matchIds.length ? matchCursor + 1 : 0} of ${matchIds.length}`
                  : ''}
              </span>
              <FxIconActionButton
                label="Older match"
                icon="previous"
                iconNode={<ChevronUp className="size-4" />}
                mini
                disabled={!matchIds.length}
                onClick={() => stepMatch(1)}
                data-testid="thread-search-prev"
              />
              <FxIconActionButton
                label="Newer match"
                icon="next"
                iconNode={<ChevronDown className="size-4" />}
                mini
                disabled={!matchIds.length}
                onClick={() => stepMatch(-1)}
                data-testid="thread-search-next"
              />
              <FxIconActionButton
                label="Close search"
                icon="close"
                iconNode={<X className="size-4" />}
                mini
                onClick={closeSearch}
                data-testid="thread-search-close"
              />
            </div>
          )}
        </div>
      )}

      <CloseThreadDialog
        open={closeDialogOpen}
        onOpenChange={setCloseDialogOpen}
        reasons={closeReasons}
        contactName={thread.name}
        onClose={onCloseConfirmed}
      />

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="relative flex min-h-0 flex-1 flex-col">
            <div
              ref={scrollerRef}
              onScroll={onScroll}
              className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-(--fx-bg)"
              data-testid="thread-scroller"
            >
              <div
                className="flex flex-col gap-2.5 p-4"
                data-testid="thread-window"
              >
                {tab === 'activities' ? (
                  <ActivityFeed
                    messages={messages}
                    events={events}
                    contactName={thread.name}
                    formatTime={formatTime}
                    timeZone={timeZone}
                  />
                ) : (
                  <>
                    {visibleMessages.length === 0 && (
                      <p className="py-8 text-center text-sm text-(--fx-ink-3)">
                        No messages yet.
                      </p>
                    )}
                    {visibleMessages.map((m, i) => (
                      <Fragment key={m.id}>
                        {(i === 0 ||
                          dateKey(visibleMessages[i - 1].createdAt, {
                            timeZone,
                          }) !== dateKey(m.createdAt, { timeZone })) && (
                          <FxDayLine iso={m.createdAt} />
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
                            isActiveMatch={
                              m.id === activeMatchId || m.id === focusMsgId
                            }
                            onReply={(msg) => {
                              setReplyTo(msg);
                            }}
                            onReact={
                              m.senderType !== 'SYSTEM' &&
                              windowOpen &&
                              capabilities.outboundReaction
                                ? (msg, emoji) => void react(msg.id, emoji)
                                : undefined
                            }
                          />
                        </div>
                      </Fragment>
                    ))}
                  </>
                )}
              </div>
            </div>

            {newBelow && tab === 'messages' && (
              <button
                type="button"
                onClick={() => toBottom(true)}
                className={cn(
                  PRESSED_CLASS,
                  'absolute inset-x-0 bottom-3 z-(--fx-z-pop) mx-auto inline-flex min-h-9 w-fit items-center gap-1.5 rounded-(--fx-r-pill) bg-(--fx-link) px-3.5 text-sm font-semibold text-(--fx-surface) shadow-[0_6px_18px_var(--fx-shade)] transition-[translate,scale] duration-(--fx-t-hover) ease-(--fx-ease-out) animate-in fade-in-0 slide-in-from-bottom-1 hover:-translate-y-0.5 active:scale-[0.97] motion-reduce:animate-none motion-reduce:hover:translate-y-0',
                )}
                data-testid="new-messages-pill"
                data-fx-new-messages=""
              >
                <ArrowDown className="size-4" aria-hidden="true" />
                New messages
              </button>
            )}
          </div>

          <Composer
            windowOpen={windowOpen}
            humanAgentWindowOpen={humanAgentWindowOpen}
            capabilities={capabilities}
            visitorPresence={visitorPresence}
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
            noChannel={hasActiveChannel === false}
          />
        </div>

        {!compact && contactPanelOpen && isDesktopPanel && (
          <div
            className="w-80 shrink-0 border-s border-(--fx-line)"
            data-testid="contact-panel-pane"
          >
            <ContactPanel
              thread={thread}
              onPatchContact={patchContact}
              onMoveLifecycle={moveLifecycle}
            />
          </div>
        )}
      </div>

      {!compact && (
        <Sheet
          open={contactPanelOpen && !isDesktopPanel}
          onOpenChange={(open) => setPanelOpen(open)}
        >
          <SheetContent
            side="right"
            className="w-full gap-0 p-0 sm:max-w-sm"
            data-testid="contact-panel-sheet"
          >
            <SheetHeader className="border-b border-(--fx-line) px-4 py-3">
              <SheetTitle>Contact</SheetTitle>
            </SheetHeader>
            <div className="min-h-0 flex-1">
              <ContactPanel
                thread={thread}
                onPatchContact={patchContact}
                onMoveLifecycle={moveLifecycle}
              />
            </div>
          </SheetContent>
        </Sheet>
      )}
    </div>
  );
}
