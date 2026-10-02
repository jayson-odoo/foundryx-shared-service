import { z } from 'zod';

/**
 * Validation for the team form (AC-TEM-02/03/04). `leadIds` is a subset of
 * `memberIds` by construction (the Leads control only ever offers currently-
 * selected Members - foolproof-UI, AC-TEM-40) but the refine is a defensive
 * net against a stale value surviving a Members removal.
 */
export const teamFormSchema = z
  .object({
    name: z.string().trim().min(1, 'Name is required.').max(120, 'Name is too long.'),
    description: z.string().trim().max(500, 'Description is too long.').optional(),
    isActive: z.boolean(),
    memberIds: z.array(z.string()),
    leadIds: z.array(z.string()),
  })
  .refine((v) => v.leadIds.every((id) => v.memberIds.includes(id)), {
    message: 'A lead must also be a member.',
    path: ['leadIds'],
  });

export type TeamFormValues = z.infer<typeof teamFormSchema>;
