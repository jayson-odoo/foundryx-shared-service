'use client';

/**
 * Omnichannel Inbox host (plan 05 §6): thin page that wires the thread list to
 * the reusable <ConversationDrawer>. Workspace-scoped; gated by
 * conversations.read.
 */
import { useEffect, useState } from 'react';

import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ConversationDrawer } from '@/components/platform/conversation-drawer';
import { useConversations } from '@/hooks/use-conversations';
import { workspaceService } from '@/services/workspace-service';

import { ThreadList } from './components/thread-list';

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

  // Deep link: ?thread=<contactId> (the bubble menu's "Copy link to message").
  // Read from window on mount instead of useSearchParams to keep the route
  // statically prerenderable. Scroll-to-?msg= is a follow-up (backlog).
  useEffect(() => {
    const thread = new URLSearchParams(window.location.search).get('thread');
    if (thread) setSelectedId(thread);
  }, []);

  return (
    <RequirePermission permission="conversations.read">
      <Container width="fluid" className="flex min-h-0 flex-1 flex-col">
        <div
          className="my-4 grid min-h-0 grid-cols-[320px_1fr] grid-rows-[minmax(0,1fr)] overflow-hidden rounded-lg border bg-background"
          style={{ height: 'calc(100vh - 180px)' }}
          data-testid="inbox-shell"
        >
          <div className="min-h-0 border-e">
            <ThreadList
              threads={threads}
              isLoading={isLoading}
              error={error}
              filters={filters}
              setFilters={setFilters}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </div>
          <div className="min-h-0">
            <ConversationDrawer contactId={selectedId} />
          </div>
        </div>
      </Container>
    </RequirePermission>
  );
}
