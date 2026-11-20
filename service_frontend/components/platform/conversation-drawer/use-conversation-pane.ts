'use client';

/**
 * Everything the conversation pane knows and does, shared by both looks
 * (today's and the Foundryx UIUX one behind the switch), so the two can never
 * drift in behaviour: the thread and its messages (`useMessages`), the
 * activity events, close reasons, templates, quick replies, workspace
 * members, assignable teams, the contact panel's remembered open state, the
 * in-thread search, the deep-linked message and the messaging-window clock.
 * Moved here unchanged from `conversation-drawer.tsx`; only the looks differ.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type {
  ConversationMessage,
  QuickReply,
  WhatsAppTemplate,
  WorkspaceMember,
} from '@/types/omnichannel';
import { ApiError } from '@/lib/api-client';
import { channelCapabilities } from '@/lib/channel-capabilities';
import { toast } from '@/lib/toast';
import { useCan } from '@/hooks/use-can';
import { useCloseReasons } from '@/hooks/use-close-reasons';
import { useDatetime } from '@/hooks/use-datetime';
import { useMediaQuery } from '@/hooks/use-media-query';
import { useMessages } from '@/hooks/use-messages';
import { useMyTeams } from '@/hooks/use-my-teams';
import { useTeams } from '@/hooks/use-teams';
import { useThreadEvents } from '@/hooks/use-thread-events';
import { useWorkspaceHasActiveChannel } from '@/hooks/use-workspace-has-active-channel';
import { conversationService } from '@/services/conversation-service';
import { workspaceService } from '@/services/workspace-service';

/** Contact panel open/closed persists per browser (plan 25, AC-CDM-34). */
const CONTACT_PANEL_STORAGE_KEY = 'omnichannel:contact-panel-open';
/** Right pane >= this width; a Sheet below it (plan 25 D14). */
const CONTACT_PANEL_BREAKPOINT = '(min-width: 1280px)';

export function useConversationPane(contactId: string | null) {
  const messagesState = useMessages(contactId);
  const { thread, messages, setStatus } = messagesState;
  const { events, reload: reloadEvents } = useThreadEvents(contactId);
  const { reasons: closeReasons } = useCloseReasons(
    thread?.workspaceId ?? null,
  );
  const [closeDialogOpen, setCloseDialogOpen] = useState(false);

  // F8 (round-3 codex triage) - `setStatus` (`useMessages`) has no internal
  // try/catch - it re-throws (matching `CloseThreadDialog`'s own `onClose`,
  // which the dialog awaits inside ITS OWN try/catch). Reopen has no dialog
  // wrapping it, so a bare `void setStatus('OPEN').then(reloadEvents)`
  // dropped any rejection (a 409 the record raced into, a network blip) with
  // zero user feedback - the button visibly does nothing, no toast, no retry
  // cue.
  const reopenThread = useCallback(async () => {
    try {
      await setStatus('OPEN');
      await reloadEvents();
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : 'Could not reopen this conversation.',
      );
    }
  }, [setStatus, reloadEvents]);

  const { timeZone, formatTime, formatDateTime } = useDatetime();
  const [tab, setTab] = useState<'messages' | 'activities'>('messages');
  const [templates, setTemplates] = useState<WhatsAppTemplate[]>([]);
  const [quickReplies, setQuickReplies] = useState<QuickReply[]>([]);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [replyTo, setReplyTo] = useState<ConversationMessage | null>(null);
  // Team Inbox (plan 28) - the assignee dropdown's Teams group. `GET /teams`
  // is gated `teams.read`, which a plain Agent (`conversations.assign` only)
  // doesn't hold - `useTeams` is only fetched for a `teams.read` holder;
  // `useMyTeams` (no `teams.read` required) always resolves so ANY caller
  // with `conversations.assign` can still assign to a team they belong to
  // (review round 1, finding 4/5/6). Union + dedupe by id. Review round 2
  // N1: only ACTIVE teams are offered - `PATCH {assignedTeamId}` 422s on an
  // inactive team (`GET /teams` lists inactive teams and `/teams/mine` has
  // no is_active filter, so both sources are filtered here).
  const canReadAllTeams = useCan().can('teams.read');
  const { teams: allTeams } = useTeams({ enabled: canReadAllTeams });
  const { teams: myTeams } = useMyTeams();
  const teams = useMemo(() => {
    const byId = new Map<string, { id: string; name: string }>();
    for (const t of [...allTeams, ...myTeams]) {
      if (!t.isActive) continue;
      if (!byId.has(t.id)) byId.set(t.id, { id: t.id, name: t.name });
    }
    return Array.from(byId.values());
  }, [allTeams, myTeams]);
  const { assignTeam } = messagesState;
  const handleAssignTeam = useCallback(
    (teamId: string | null) => {
      assignTeam(teamId).catch((e: unknown) => {
        toast.error(
          e instanceof Error
            ? e.message
            : 'Could not update the team assignment.',
        );
      });
    },
    [assignTeam],
  );

  // Contact panel (plan 25, AC-CDM-34) - open state persists per browser;
  // >=1280px renders a right pane, below it a Sheet (D14). Never shown in
  // compact/embed mode (the header - and this toggle - is hidden there).
  const [contactPanelOpen, setContactPanelOpen] = useState(false);
  const isDesktopPanel = useMediaQuery(CONTACT_PANEL_BREAKPOINT);
  useEffect(() => {
    try {
      setContactPanelOpen(
        window.localStorage.getItem(CONTACT_PANEL_STORAGE_KEY) === '1',
      );
    } catch {
      // localStorage unavailable (private browsing etc.) - default closed.
    }
  }, []);
  const setPanelOpen = useCallback((next: boolean) => {
    setContactPanelOpen(next);
    try {
      window.localStorage.setItem(CONTACT_PANEL_STORAGE_KEY, next ? '1' : '0');
    } catch {
      // localStorage unavailable - the toggle still works for this session
    }
  }, []);
  const toggleContactPanel = useCallback(
    () => setPanelOpen(!contactPanelOpen),
    [contactPanelOpen, setPanelOpen],
  );

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
  // Window state is derived through the capability record per channel type
  // (plan 32 / A7a) instead of a hardcoded WhatsApp-only boolean. WhatsApp
  // reads the SAME `cswExpiresAt` instant it always has (D-A7-5/R7 - byte-
  // identical); every other type reads the generalized `windowExpiresAt`.
  const capabilities = channelCapabilities(thread?.channelType ?? 'WHATSAPP');
  // Lane SS-CHANNEL-SKIP - `false` only when the workspace verifiably has no
  // active channel (null = unknown keeps the window-driven composer).
  const hasActiveChannel = useWorkspaceHasActiveChannel(thread?.workspaceId);
  const windowOpen = useMemo(() => {
    const iso =
      thread?.channelType === 'WHATSAPP'
        ? thread?.cswExpiresAt
        : thread?.windowExpiresAt;
    return !!iso && Date.parse(iso) > nowTick;
  }, [
    thread?.channelType,
    thread?.cswExpiresAt,
    thread?.windowExpiresAt,
    nowTick,
  ]);
  const humanAgentWindowOpen = useMemo(() => {
    if (capabilities.reengageMode !== 'human_agent') return false;
    const iso = thread?.humanAgentExpiresAt;
    return !!iso && Date.parse(iso) > nowTick;
  }, [capabilities.reengageMode, thread?.humanAgentExpiresAt, nowTick]);
  // Web chat presence marker (plan 34 / A7b, D-A7B-19/AC-WEB-43) - the
  // window-less channel type's stand-in for the window banner, computed here
  // (not in the composer) so the composer stays free of a timezone/session
  // dependency. `online` is a 2-minute recency heuristic - a UX mirror only,
  // never an authorization fact (`reengageMode: 'none'` never locks anyway).
  const visitorPresence = useMemo(() => {
    if (capabilities.reengageMode !== 'none') return null;
    const iso = thread?.visitorLastSeenAt;
    if (!iso) return null;
    const online = nowTick - Date.parse(iso) < 2 * 60_000;
    return {
      online,
      label: online ? 'Online now' : `Last seen ${formatDateTime(iso)}`,
    };
  }, [
    capabilities.reengageMode,
    thread?.visitorLastSeenAt,
    nowTick,
    formatDateTime,
  ]);

  useEffect(() => {
    if (!thread?.channelId) return setTemplates([]);
    conversationService
      .listTemplates(thread.channelId)
      .then(setTemplates)
      .catch(() => setTemplates([]));
  }, [thread?.channelId]);

  useEffect(() => {
    if (!thread?.workspaceId) return;
    conversationService
      .listQuickReplies(thread.workspaceId)
      .then(setQuickReplies)
      .catch(() => setQuickReplies([]));
    workspaceService
      .getMembers(thread.workspaceId)
      .then(setMembers)
      .catch(() => setMembers([]));
  }, [thread?.workspaceId]);

  // Plan 27: the Activities tab renders <ActivityFeed> (notes + events
  // merged) instead of the message list - in-thread search stays a
  // Messages-tab feature (the search button is hidden on Activities, so
  // `visibleMessages` only needs to serve the Messages tab).
  const visibleMessages = messages;

  // In-thread search matches (newest → oldest, like WhatsApp's ↑ navigation).
  const activeSearch = searchOpen ? searchTerm.trim().toLowerCase() : '';
  const matchIds = useMemo(() => {
    if (!activeSearch) return [];
    return visibleMessages
      .filter((m) => (m.body ?? '').toLowerCase().includes(activeSearch))
      .map((m) => m.id)
      .reverse();
  }, [visibleMessages, activeSearch]);
  const activeMatchId =
    matchIds[Math.min(matchCursor, Math.max(matchIds.length - 1, 0))] ?? null;
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
      messageRefs.current
        .get(activeMatchId)
        ?.scrollIntoView({ block: 'center' });
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

  const closeSearch = useCallback(() => {
    setSearchOpen(false);
    setSearchTerm('');
    setMatchCursor(0);
  }, []);

  return {
    ...messagesState,
    events,
    reloadEvents,
    closeReasons,
    closeDialogOpen,
    setCloseDialogOpen,
    reopenThread,
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
    handleAssignTeam,
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
  };
}

export type ConversationPaneState = ReturnType<typeof useConversationPane>;
