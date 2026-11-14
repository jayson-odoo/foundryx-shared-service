'use client';

import { useMemo } from 'react';
import { Trash2 } from 'lucide-react';
import { toast } from '@/lib/toast';
import { ApiError } from '@/lib/api-client';
import type { ResourceAction, ResourceActionRuntime } from '@/components/platform/resource-list';
import { contactService } from '@/services/contact-service';
import type { ContactListItem } from '@/types/omnichannel';

/**
 * ONE definition of "Erase contact" (plan 56 C, AC-56-52), shared by the
 * contacts list row menu and the contact detail menu. Irreversible hard
 * delete, so it is a disclosed typed-confirm carve-out (`ERASE`), never the
 * deferred grace window. Counts in the body come from the row itself.
 */
export type ContactEraseSurface = 'row' | 'form';

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function useContactEraseAction(
  surface: ContactEraseSurface,
  onErased: (runtime: ResourceActionRuntime) => void,
): ResourceAction<ContactListItem> {
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
        },
      },
      run: async (rows, runtime) => {
        const target = rows[0];
        if (!target) return;
        try {
          await contactService.eraseContact(target.id);
        } catch (error) {
          toast.error(error instanceof ApiError ? error.message : 'Could not erase the contact.');
          return;
        }
        toast.success('Contact erased');
        onErased(runtime);
      },
    }),
    [surface, onErased],
  );
}
