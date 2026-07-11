'use client';

/**
 * Embed thread view — a single chromeless conversation pane (scope
 * `thread:<contactId>`). Reuses the SAME <ConversationDrawer> the protected
 * inbox renders (rich parity comes free — AC-11H-16); no reduced renderer.
 */
import { ConversationDrawer } from '@/components/platform/conversation-drawer';

export function EmbedThreadView({ contactId }: { contactId: string | null }) {
  return (
    <div className="min-h-0 flex-1 overflow-hidden">
      <ConversationDrawer contactId={contactId} />
    </div>
  );
}
