'use client';

/**
 * Omnichannel Inbox host (plan 05 §6; plan 27 adds the view rail + filter bar
 * + a below-`lg` single-pane switch, D-A3-15). Thin page that wires the rail,
 * the thread list and the reusable <ConversationDrawer>. Workspace-scoped;
 * gated by conversations.read.
 */
import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft } from 'lucide-react';

import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ConversationDrawer } from '@/components/platform/conversation-drawer';
import { Button } from '@/components/ui/button';
import { useConversations } from '@/hooks/use-conversations';
import { useMediaQuery } from '@/hooks/use-media-query';
import { workspaceService } from '@/services/workspace-service';

import { InboxFilterBar } from './components/inbox-filter-bar';
import { InboxViewRail } from './components/inbox-view-rail';
import { ThreadList } from './components/thread-list';

/** Rail sits beside the list at >=1024px (`lg`); below it the shell is ONE
 *  pane (AC-IVE-24) and the rail collapses into a View `SearchSelect`. */
const DESKTOP_RAIL_QUERY = '(min-width: 1024px)';

export default function InboxPage() {
  // Resolve the workspace (default first). A workspace switcher rides in when
  // multi-workspace inbox UX lands (plan 05 keeps the host thin).
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  useEffect(() => {
    workspaceService
      .list({ page: 0, pageSize: 50 })
      .then((res) => {
        const ws = res.data.find((w) => w.isDefault) ?? res.data[0];
        setWorkspaceId(ws?.id ?? null);
      })
      .catch(() => setWorkspaceId(null));
  }, []);

  const { threads, isLoading, error, filters, setFilters } = useConversations(workspaceId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const isDesktop = useMediaQuery(DESKTOP_RAIL_QUERY);

  // Deep link: ?thread=<contactId> is the source of truth for the open
  // conversation - opening a thread pushes it into the URL (shareable +
  // debuggable), and browser back/forward re-selects. Read from window/history
  // instead of useSearchParams to keep the route statically prerenderable.
  useEffect(() => {
    const sync = () => setSelectedId(new URLSearchParams(window.location.search).get('thread'));
    sync(); // initial deep link
    window.addEventListener('popstate', sync);
    return () => window.removeEventListener('popstate', sync);
  }, []);

  const openThread = useCallback((id: string | null) => {
    setSelectedId(id);
    const url = new URL(window.location.href);
    if (id) url.searchParams.set('thread', id);
    else url.searchParams.delete('thread');
    // Same thread re-click = no history spam; a new thread = a back-navigable entry.
    if (id !== new URLSearchParams(window.location.search).get('thread')) {
      window.history.pushState(null, '', url);
    }
  }, []);

  // Below `lg` the shell shows ONE pane: the list (with the View select +
  // filter bar above it), or the open conversation with a back control
  // (AC-IVE-24). At >=lg both panes plus the rail render side by side.
  const showingThreadOnMobile = !isDesktop && !!selectedId;

  return (
    <RequirePermission permission="conversations.read">
      <Container width="fluid" className="flex min-h-0 flex-1 flex-col">
        <div
          className={
            isDesktop
              ? 'my-4 grid min-h-0 grid-cols-[200px_320px_1fr] grid-rows-[minmax(0,1fr)] overflow-hidden rounded-lg border bg-background'
              : 'my-4 grid min-h-0 grid-rows-[minmax(0,1fr)] overflow-hidden rounded-lg border bg-background'
          }
          style={{ height: 'calc(100vh - 180px)' }}
          data-testid="inbox-shell"
        >
          {isDesktop && (
            <div className="min-h-0 border-e">
              <InboxViewRail workspaceId={workspaceId} filters={filters} setFilters={setFilters} variant="sidebar" />
            </div>
          )}

          {(isDesktop || !showingThreadOnMobile) && (
            <div className="flex min-h-0 min-w-0 flex-col border-e">
              {!isDesktop && (
                <div className="border-b p-2">
                  <InboxViewRail workspaceId={workspaceId} filters={filters} setFilters={setFilters} variant="select" />
                </div>
              )}
              <div className="border-b p-2">
                <InboxFilterBar filters={filters} setFilters={setFilters} />
              </div>
              <div className="min-h-0 flex-1">
                <ThreadList
                  threads={threads}
                  isLoading={isLoading}
                  error={error}
                  filters={filters}
                  setFilters={setFilters}
                  selectedId={selectedId}
                  onSelect={openThread}
                />
              </div>
            </div>
          )}

          {(isDesktop || showingThreadOnMobile) && (
            <div className="flex min-h-0 min-w-0 flex-col">
              {!isDesktop && (
                <div className="border-b p-1.5">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => openThread(null)}
                    aria-label="Back to conversations"
                    data-testid="inbox-back"
                  >
                    <ArrowLeft className="size-4" />
                    Conversations
                  </Button>
                </div>
              )}
              <div className="min-h-0 flex-1">
                <ConversationDrawer contactId={selectedId} />
              </div>
            </div>
          )}
        </div>
      </Container>
    </RequirePermission>
  );
}
