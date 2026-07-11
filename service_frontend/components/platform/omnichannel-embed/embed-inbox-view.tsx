'use client';

/**
 * Embed inbox view — the full chromeless workspace inbox (scope `inbox`).
 * Reuses the exact ThreadList + ConversationDrawer composition of the protected
 * inbox page; the workspace comes from the embed session (no workspaceService
 * call — a thread-scoped-agent's token might not list workspaces).
 *
 * Responsive (AC-11H-17): side-by-side at ≥lg; a master/detail single pane on
 * mobile (selecting a thread swaps the list for the drawer + a back control),
 * so it fits a narrow side panel and a 375px phone with no horizontal scroll.
 */
import { useState } from 'react';
import { ChevronLeft } from 'lucide-react';

import { ConversationDrawer } from '@/components/platform/conversation-drawer';
import { Button } from '@/components/ui/button';
import { useConversations } from '@/hooks/use-conversations';
import { cn } from '@/lib/utils';

import { ThreadList } from '@/app/(protected)/omnichannel/inbox/components/thread-list';

export function EmbedInboxView({ workspaceId }: { workspaceId: string }) {
  const { threads, isLoading, error, filters, setFilters } = useConversations(workspaceId);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[minmax(0,1fr)] overflow-hidden bg-background lg:grid-cols-[320px_1fr]">
      <div className={cn('min-h-0 border-e', selectedId ? 'hidden lg:block' : 'block')}>
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
      <div className={cn('min-h-0 flex-col', selectedId ? 'flex' : 'hidden lg:flex')}>
        <div className="flex items-center border-b p-2 lg:hidden">
          <Button variant="ghost" size="sm" onClick={() => setSelectedId(null)}>
            <ChevronLeft className="size-4" />
            Conversations
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-hidden">
          <ConversationDrawer contactId={selectedId} />
        </div>
      </div>
    </div>
  );
}
