'use client';

/**
 * Contact panel (plan 25, AC-CDM-34/35) - Details / Lifecycle / Tags stacked
 * as three always-visible sections (foolproof-UI - nothing hidden behind an
 * extra click). Renders as a right pane (>=1280px) or a Sheet (<1280px) from
 * the drawer header toggle; hidden in compact/embed modes (D14).
 */
import { useContactFields } from '@/hooks/use-contact-fields';
import { useContactTags } from '@/hooks/use-contact-tags';
import type { ConversationThread, PatchContactInput } from '@/types/omnichannel';
import { ContactDetailsForm } from './contact-details-form';
import { LifecycleMove } from './lifecycle-move';
import { TagChips } from './tag-chips';

export interface ContactPanelProps {
  thread: ConversationThread;
  onPatchContact: (patch: PatchContactInput) => Promise<ConversationThread>;
  onMoveLifecycle: (toStatusId: string) => Promise<ConversationThread>;
}

export function ContactPanel({ thread, onPatchContact, onMoveLifecycle }: ContactPanelProps) {
  const { fields } = useContactFields(thread.workspaceId);
  const { tags: workspaceTags } = useContactTags(thread.workspaceId);

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4" data-testid="contact-panel">
      <ContactDetailsForm thread={thread} fields={fields} onSave={onPatchContact} />
      <div className="border-t pt-4">
        <LifecycleMove contactId={thread.id} lifecycle={thread.lifecycle} onMove={onMoveLifecycle} />
      </div>
      <div className="border-t pt-4">
        <TagChips
          tags={thread.tags}
          workspaceTags={workspaceTags}
          onChange={(tagIds) => onPatchContact({ tagIds })}
        />
      </div>
    </div>
  );
}
