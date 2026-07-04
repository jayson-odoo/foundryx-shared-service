import { z } from 'zod';

/** Validation for the user form. Email is required only at create (read-only after). */
export const userFormSchema = z.object({
  name: z.string().trim().min(1, 'Name is required.').max(120, 'Name is too long.'),
  email: z.string().trim().email('Enter a valid email.'),
  roleIds: z.array(z.string()),
  status: z.enum(['ACTIVE', 'INACTIVE', 'BLOCKED']),
});

export type UserFormValues = z.infer<typeof userFormSchema>;
