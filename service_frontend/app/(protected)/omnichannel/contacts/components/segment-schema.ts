import { z } from 'zod';

/**
 * Validation for the "Save as segment" / segment-rename dialogs (AC-CTM-06,
 * AC-CTM-47). Plain (non-optional) string fields, defaulted at the form-state
 * level (`defaultSegmentFormValues`) - `.optional().default()` on the schema
 * itself makes zodResolver's input/output generics diverge and RHF reject the
 * resolver at the type level.
 */
export const segmentFormSchema = z.object({
  name: z.string().trim().min(1, 'Name is required.').max(120, 'Name is too long.'),
  description: z.string().trim().max(500, 'Description is too long.'),
});

export type SegmentFormValues = z.infer<typeof segmentFormSchema>;

export function defaultSegmentFormValues(): SegmentFormValues {
  return { name: '', description: '' };
}
