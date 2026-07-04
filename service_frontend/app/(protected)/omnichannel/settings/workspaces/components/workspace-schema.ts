import { z } from 'zod';

export const workspaceFormSchema = z.object({
  name: z.string().trim().min(1, 'Name is required').max(80, 'Name is too long'),
  status: z.enum(['ACTIVE', 'INACTIVE']),
});

export type WorkspaceFormValues = z.infer<typeof workspaceFormSchema>;
