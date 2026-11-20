/** Save/rename-view dialog schema (plan 27, AC-IVE-18/22). `isShared` is a
 *  plain bool here - the dialog HIDES the switch (never disables it checked)
 *  for a caller without `inbox_views.manage`, so an unauthorized value never
 *  reaches the schema in practice; the server is the real gate (D-A3-11). */
import { z } from 'zod';

export const inboxViewSchema = z.object({
  name: z.string().trim().min(1, 'Name is required').max(200, 'Name is too long'),
  isShared: z.boolean(),
});

export type InboxViewFormValues = z.infer<typeof inboxViewSchema>;

export function defaultInboxViewFormValues(): InboxViewFormValues {
  return { name: '', isShared: false };
}
