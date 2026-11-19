'use client';

import { useMemo } from 'react';
import { Trash2 } from 'lucide-react';
import { toast } from '@/lib/toast';
import { ApiError } from '@/lib/api-client';
import type { ResourceAction, ResourceActionRuntime } from '@/components/platform/resource-list';
import { useFx } from '@/hooks/use-fx';
import { contactService } from '@/services/contact-service';
import type { ContactListItem } from '@/types/omnichannel';
import { useFxActorName } from './contacts-fx';

/**
 * ONE definition of "Erase contact" (plan 56 C, AC-56-52), shared by the
 * contacts list row menu and the contact detail menu. Irreversible hard
 * delete, so it is a disclosed typed-confirm carve-out (`ERASE`), never the
 * deferred grace window. Counts in the body come from the row itself.
 *
 * Foundryx UIUX switch on (answers.md: "type the record name/number to
 * delete, replacing the hold"): the confirm asks for the contact's own name
 * (`contactEraseExpected`), its safe button is "Keep contact", and the done
 * toast names who was erased with what (no Undo: nothing brings it back).
 */
export type ContactEraseSurface = 'row' | 'form';

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** What the switch-on confirm asks to type: the contact's name, else its
 *  phone or email, else "ERASE" for a contact with none of them. Matched
 *  ignoring case and spaces by the shared confirm. */
export function contactEraseExpected(row: Pick<ContactListItem, 'name' | 'phone' | 'email'> | undefined): string {
  return row?.name?.trim() || row?.phone?.trim() || row?.email?.trim() || 'ERASE';
}

/** The switch-on safe button. */
export const CONTACT_ERASE_KEEP_LABEL = 'Keep contact';

/** The switch-on done toast's words (pure). */
export function contactErasedWords(name: string, messages: number, files: number): { what: string; howMany: string } {
  return {
    what: `${name} erased`,
    howMany: `with ${plural(messages, 'message', 'messages')} and ${plural(files, 'file', 'files')}`,
  };
}

export function useContactEraseAction(
  surface: ContactEraseSurface,
  onErased: (runtime: ResourceActionRuntime) => void,
): ResourceAction<ContactListItem> {
  const fx = useFx();
  const actor = useFxActorName();
  return useMemo<ResourceAction<ContactListItem>>(
    () => ({
      id: 'erase-contact',
      label: 'Erase contact',
      icon: Trash2,
      tone: 'destructive',
      permission: 'contacts.erase',
      surfaces: surface === 'row' ? { row: true } : { form: true },
      confirm: {
        title: (rows) => `Erase ${rows[0]?.name ?? 'contact'}?`,
        description: (rows) =>
          `This erases the contact, ${plural(rows[0]?.messageCount ?? 0, 'message', 'messages')} and ${plural(rows[0]?.fileCount ?? 0, 'file', 'files')}. It cannot be undone.`,
        confirmLabel: 'Erase contact',
        input: {
          expected: () => 'ERASE',
          hint: () => 'Type "ERASE" to confirm.',
          fxExpected: (rows) => contactEraseExpected(rows[0]),
        },
        fxKeepLabel: CONTACT_ERASE_KEEP_LABEL,
      },
      run: async (rows, runtime) => {
        const target = rows[0];
        if (!target) return;
        let result: Awaited<ReturnType<typeof contactService.eraseContact>> | undefined;
        try {
          result = await contactService.eraseContact(target.id);
        } catch (error) {
          toast.error(error instanceof ApiError ? error.message : 'Could not erase the contact.');
          return;
        }
        if (fx) {
          const words = contactErasedWords(
            target.name,
            result?.messages ?? target.messageCount ?? 0,
            result?.files ?? target.fileCount ?? 0,
          );
          toast.fxDone({ ...words, byWhom: actor });
        } else {
          toast.success('Contact erased');
        }
        onErased(runtime);
      },
    }),
    [surface, onErased, fx, actor],
  );
}
