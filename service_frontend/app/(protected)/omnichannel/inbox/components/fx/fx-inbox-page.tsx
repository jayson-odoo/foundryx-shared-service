'use client';

/**
 * The inbox with the Foundryx UIUX switch on (slice W1-INBOX, mock "Inbox").
 *
 * - A slim page header ("Inbox" and its trail). The open conversation owns
 *   the page's red action (Close conversation, or Reopen), which the pane
 *   hands to this header (`fxPageHeader`); it hides while a dialog is open.
 * - Desktop (1024px and up): the three panes are kept (views rail 200px,
 *   list 320px, the conversation in the rest), with no hover-widen (owner
 *   choice).
 * - Narrower: browser-style tabs, "Conversations" and the open chat (owner
 *   choice, as mocked). Both stay mounted, so each keeps its scroll and
 *   state; opening a conversation switches to its tab.
 * - After 5 s without the live feed, the system banner says so; once it is
 *   back the list is fetched again so nothing missed stays missing.
 *
 * Everything else is the legacy page's own state (`useInboxPage`): the same
 * workspace, filters, list requests, live feed, `?thread=` and Back.
 */
import { useState } from 'react';
import type { ConversationThread } from '@/types/omnichannel';
import { cn } from '@/lib/utils';
import type { ConversationFilters } from '@/hooks/use-conversations';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { useConnectionBanner } from '@/components/fx/banners/use-connection-banner';
import { ConversationDrawer } from '@/components/platform/conversation-drawer';
import { PageHeader } from '@/components/platform/page-header';
import { InboxFilterBar } from '../inbox-filter-bar';
import { railSelectionPatch } from '../inbox-rail-entries';
import { InboxViewRail } from '../inbox-view-rail';
import { ThreadList } from '../thread-list';
import { useInboxPage } from '../use-inbox-page';

/** The filters "Clear filters" goes back to: the All entry and the bar's
 *  defaults. The sort stays (it orders, it never hides a row). */
export function fxClearedFilters(): Partial<ConversationFilters> {
  return {
    ...railSelectionPatch({ kind: 'default', key: 'all', label: 'All' }),
    status: 'ALL',
    statusExplicit: false,
    priority: 'ALL',
    unreplied: false,
    search: '',
  };
}

/** The open chat's tab name: the contact's first name, as mocked. */
export function fxChatTabLabel(thread: ConversationThread | undefined): string {
  if (!thread) return 'Chat';
  return thread.firstName?.trim() || thread.name.split(/\s+/)[0] || thread.name;
}

type PhoneTab = 'list' | 'chat';

const SHELL_HEIGHT = { height: 'calc(100dvh - 230px)' };
const PHONE_HEIGHT = { height: 'calc(100dvh - 190px)' };

export function FxInboxPage() {
  const {
    workspaceId,
    conversations: {
      threads,
      isLoading,
      error,
      filters,
      setFilters,
      reload,
      isConnected,
    },
    selectedId,
    isDesktop,
    openThread,
  } = useInboxPage();

  // Lost connection: the banner after 5 s. The list fetches again by itself
  // whenever the feed is back after a drop (useConversations, both looks).
  useConnectionBanner(isConnected);

  // Phone tabs: opening a conversation shows its tab; closing it (Back)
  // returns to the list. Choosing a tab only switches what is shown.
  const [tab, setTab] = useState<PhoneTab>('list');
  const [tabFor, setTabFor] = useState<string | null>(null);
  if (selectedId !== tabFor) {
    setTabFor(selectedId);
    setTab(selectedId ? 'chat' : 'list');
  }

  const clearFilters = () => {
    setFilters(fxClearedFilters());
    const url = new URL(window.location.href);
    url.searchParams.delete('view');
    window.history.replaceState(null, '', url);
  };

  const list = (
    <ThreadList
      threads={threads}
      isLoading={isLoading}
      error={error}
      filters={filters}
      setFilters={setFilters}
      selectedId={selectedId}
      onSelect={openThread}
      onRetry={reload}
      onClearFilters={clearFilters}
    />
  );
  const pane = <ConversationDrawer contactId={selectedId} fxPageHeader />;

  return (
    <RequirePermission permission="conversations.read">
      <Container width="fluid" className="flex min-h-0 flex-1 flex-col">
        <PageHeader title="Inbox" />
        {isDesktop ? (
          <div
            className="mb-4 grid min-h-[480px] grid-cols-[200px_320px_minmax(0,1fr)] grid-rows-[minmax(0,1fr)] overflow-hidden rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface)"
            style={SHELL_HEIGHT}
            data-testid="inbox-shell"
            data-fx-inbox=""
          >
            <div className="min-h-0 border-e border-(--fx-line)">
              <InboxViewRail
                workspaceId={workspaceId}
                filters={filters}
                setFilters={setFilters}
                variant="sidebar"
              />
            </div>
            <div className="flex min-h-0 min-w-0 flex-col border-e border-(--fx-line)">
              <div className="border-b border-(--fx-line) p-2.5">
                <InboxFilterBar filters={filters} setFilters={setFilters} />
              </div>
              <div className="min-h-0 flex-1">{list}</div>
            </div>
            <div className="flex min-h-0 min-w-0 flex-col">
              <div className="min-h-0 flex-1">{pane}</div>
            </div>
          </div>
        ) : (
          <div
            className="mb-3 flex min-h-[420px] min-w-0 flex-col overflow-hidden rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-line)"
            style={PHONE_HEIGHT}
            data-testid="inbox-shell"
            data-fx-inbox=""
          >
            <div
              role="tablist"
              aria-label="Inbox panels"
              className="flex min-w-0 gap-0.5 px-2 pt-2"
            >
              {(
                [
                  ['list', 'Conversations'],
                  [
                    'chat',
                    fxChatTabLabel(threads.find((t) => t.id === selectedId)),
                  ],
                ] as const
              ).map(([key, label]) => {
                const on = tab === key;
                return (
                  <button
                    key={key}
                    type="button"
                    role="tab"
                    id={`inbox-tab-${key}`}
                    aria-selected={on}
                    aria-controls={`inbox-panel-${key}`}
                    onClick={() => setTab(key)}
                    className={cn(
                      PRESSED_CLASS,
                      'inline-flex min-h-11 min-w-0 items-center gap-1.5 rounded-t-(--fx-r-m) px-3 text-sm font-semibold transition-colors duration-(--fx-t-hover) ease-(--fx-ease-out)',
                      on
                        ? 'flex-1 bg-(--fx-surface) text-(--fx-ink)'
                        : 'bg-(--fx-surface-2) text-(--fx-ink-2) hover:text-(--fx-ink)',
                    )}
                    data-testid={`inbox-tab-${key}`}
                  >
                    <span className="truncate">{label}</span>
                    {key === 'list' && threads.length > 0 && (
                      <span className="inline-grid h-5 min-w-5 shrink-0 place-items-center rounded-(--fx-r-pill) bg-(--fx-link) px-1.5 text-xs tabular-nums text-(--fx-surface)">
                        {threads.length}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
            <div
              role="tabpanel"
              id="inbox-panel-list"
              aria-labelledby="inbox-tab-list"
              hidden={tab !== 'list'}
              className="min-h-0 flex-1 flex-col bg-(--fx-surface) animate-in fade-in-0 duration-(--fx-t-hover) motion-reduce:animate-none data-[shown=true]:flex"
              data-shown={tab === 'list'}
            >
              <div className="flex flex-col gap-2 border-b border-(--fx-line) p-2.5">
                <InboxViewRail
                  workspaceId={workspaceId}
                  filters={filters}
                  setFilters={setFilters}
                  variant="select"
                />
                <InboxFilterBar filters={filters} setFilters={setFilters} />
              </div>
              <div className="min-h-0 flex-1">{list}</div>
            </div>
            <div
              role="tabpanel"
              id="inbox-panel-chat"
              aria-labelledby="inbox-tab-chat"
              hidden={tab !== 'chat'}
              className="min-h-0 flex-1 flex-col bg-(--fx-surface) animate-in fade-in-0 duration-(--fx-t-hover) motion-reduce:animate-none data-[shown=true]:flex"
              data-shown={tab === 'chat'}
            >
              <div className="min-h-0 flex-1">{pane}</div>
            </div>
          </div>
        )}
      </Container>
    </RequirePermission>
  );
}
