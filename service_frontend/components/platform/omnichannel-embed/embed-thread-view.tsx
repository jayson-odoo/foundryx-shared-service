'use client';

/**
 * Embed thread view — a single chromeless conversation pane (scope
 * `thread:<contactId>`). Reuses the SAME <ConversationDrawer> the protected
 * inbox renders (rich parity comes free — AC-11H-16); no reduced renderer.
 * `compact` = messages + composer only (no contact header / tabs / search /
 * assign / lifecycle) so it drops into a narrow lead-page side panel; the FULL
 * variant (`compact={false}`) keeps the contact header / assign / lifecycle.
 */
import { ConversationDrawer } from '@/components/platform/conversation-drawer';

export function EmbedThreadView({
  contactId,
  compact = true,
}: {
  contactId: string | null;
  compact?: boolean;
}) {
  return (
    <div className="min-h-0 flex-1 overflow-hidden">
      <ConversationDrawer contactId={contactId} compact={compact} />
    </div>
  );
}
