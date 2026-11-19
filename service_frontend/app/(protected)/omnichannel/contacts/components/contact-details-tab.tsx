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
import { useFx } from '@/hooks/use-fx';
import { FxContactPanel } from './fx-contact-panel';

export interface ContactDetailsTabProps {
  contactId: string;
  /** Foundryx UIUX switch only: told when the Details section starts or
   *  stops editing, so the record hides its arrows meanwhile. */
  onEditingChange?: (editing: boolean) => void;
}

/**
 * Foundryx UIUX switch on: the same data through the new-look panel
 * (`fx-contact-panel.tsx`). Off: the original tab, markup unchanged.
 */
export function ContactDetailsTab(props: ContactDetailsTabProps) {
  return useFx() ? (
    <FxContactDetailsTab {...props} />
  ) : (
    <ContactDetailsTabLegacy contactId={props.contactId} />
  );
}

function FxContactDetailsTab({
  contactId,
  onEditingChange,
}: ContactDetailsTabProps) {
  const { thread, isLoading, error, patchContact, moveLifecycle } =
    useMessages(contactId);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16 text-(--fx-ink-3)">
        <LoaderCircleIcon
          aria-label="Loading"
          className="size-6 animate-spin"
        />
      </div>
    );
  }

  if (error || !thread) {
    return (
      <div className="flex flex-col items-center gap-2 py-16 text-center text-(--fx-ink-2)">
        <Info aria-hidden="true" className="size-8 text-(--fx-ink-3)" />
        <p className="text-sm font-semibold">Contact not found.</p>
      </div>
    );
  }

  return (
    <FxContactPanel
      thread={thread}
      onPatchContact={patchContact}
      onMoveLifecycle={moveLifecycle}
      onEditingChange={onEditingChange}
    />
  );
}

function ContactDetailsTabLegacy({ contactId }: { contactId: string }) {
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
