import { z } from 'zod';

/** Validation for the role form. Name required; permission keys are a flat list. */
export const roleFormSchema = z.object({
  name: z.string().trim().min(1, 'Name is required.').max(80, 'Name is too long.'),
  description: z.string().trim().max(240, 'Description is too long.'),
  permissionKeys: z.array(z.string()),
  /** System roles are protected from deletion; admin-toggleable here. */
  isSystem: z.boolean(),
});

export type RoleFormValues = z.infer<typeof roleFormSchema>;
