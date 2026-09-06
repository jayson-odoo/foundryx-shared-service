import { z } from 'zod';

/**
 * Create-contact form validation (D-A2-4, AC-CTM-08). Phone is required and
 * create-only; system fields mirror `contact-details-form.tsx`'s shape so the
 * two stay easy to reconcile. Plain (non-optional) string fields, defaulted
 * at the form-state level (`defaultContactCreateValues`) - `.optional()` on
 * the schema itself makes zodResolver's input/output generics diverge and
 * RHF reject the resolver at the type level. Custom-field values are
 * validated at submit by the mock/real service (typed per the registry) -
 * this schema only enforces the client-visible shape.
 */
export const contactCreateSchema = z.object({
  firstName: z.string().trim().max(120, 'Too long.'),
  lastName: z.string().trim().max(120, 'Too long.'),
  phone: z.string().trim().min(1, 'Phone is required.'),
  email: z.string().trim().max(255, 'Too long.'),
  language: z.string().trim().max(35, 'Too long.'),
  countryCode: z.string().trim().max(2, 'Use a 2-letter code.'),
  lifecycleStatusId: z.string().nullable(),
  tagIds: z.array(z.string()),
});

export type ContactCreateValues = z.infer<typeof contactCreateSchema>;

export function defaultContactCreateValues(): ContactCreateValues {
  return {
    firstName: '',
    lastName: '',
    phone: '',
    email: '',
    language: '',
    countryCode: '',
    lifecycleStatusId: null,
    tagIds: [],
  };
}
