'use client';

/**
 * Detail-page Details tab (AC-CTM-07) - reuses the A1 `ContactPanel`
 * (which already composes `contact-details-form` + `lifecycle-move` +
 * `tag-chips`) as-is, backed by the SAME `useMessages` hook the Conversation
 * tab's `<ConversationDrawer>` uses internally - one real data source, no
 * second chat/contact implementation. Synthetic S0 rows (mock-only ids, no
 * backend record yet) surface the real 404 as a plain notice rather than a
 * crash - S1's backend swap makes every row real.
 */
import { Info, LoaderCircleIcon } from 'lucide-react';
import { ContactPanel } from '@/components/platform/conversation-drawer';
import { useMessages } from '@/hooks/use-messages';

export function ContactDetailsTab({ contactId }: { contactId: string }) {
  const { thread, isLoading, error, patchContact, moveLifecycle } = useMessages(contactId);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground">
        <LoaderCircleIcon className="size-6 animate-spin" />
      </div>
    );
  }

  if (error || !thread) {
    return (
      <div className="flex flex-col items-center gap-2 py-16 text-center text-muted-foreground">
        <Info className="size-8" />
        <p className="text-sm font-medium">Contact not found.</p>
      </div>
    );
  }

  return <ContactPanel thread={thread} onPatchContact={patchContact} onMoveLifecycle={moveLifecycle} />;
}
