'use client';

/**
 * Omnichannel Inbox host (plan 05 §6; plan 27 adds the view rail + filter bar
 * + a below-`lg` single-pane switch, D-A3-15). Thin page that wires the rail,
 * the thread list and the reusable <ConversationDrawer>. Workspace-scoped;
 * gated by conversations.read.
 */
import { ArrowLeft } from 'lucide-react';

import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ConversationDrawer } from '@/components/platform/conversation-drawer';
import { Button } from '@/components/ui/button';
import { useFx } from '@/hooks/use-fx';

import { FxInboxPage } from './components/fx/fx-inbox-page';
import { InboxFilterBar } from './components/inbox-filter-bar';
import { InboxViewRail } from './components/inbox-view-rail';
import { ThreadList } from './components/thread-list';
import { useInboxPage } from './components/use-inbox-page';

export default function InboxPage() {
  // Foundryx UIUX switch (playbook-uiux.md): the slim page header, the
  // playbook list and phone tabs. Off renders the legacy body below, unchanged.
  return useFx() ? <FxInboxPage /> : <InboxPageLegacy />;
}

function InboxPageLegacy() {
  const {
    workspaceId,
    conversations: { threads, isLoading, error, filters, setFilters },
    selectedId,
    isDesktop,
    openThread,
    backToList,
  } = useInboxPage();

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
          style={{ height: 'calc(100dvh - 180px)' }}
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
                    onClick={backToList}
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
