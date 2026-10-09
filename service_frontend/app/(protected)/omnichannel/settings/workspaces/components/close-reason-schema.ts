/** Close-reason create/edit dialog schema (plan 27, AC-IVE-25). */
import { z } from 'zod';

export const closeReasonSchema = z.object({
  name: z.string().trim().min(1, 'Name is required').max(200, 'Name is too long'),
  sortOrder: z.number().int().min(0),
  isActive: z.boolean(),
});

export type CloseReasonFormValues = z.infer<typeof closeReasonSchema>;

export function defaultCloseReasonFormValues(nextSortOrder: number): CloseReasonFormValues {
  return { name: '', sortOrder: nextSortOrder, isActive: true };
}
