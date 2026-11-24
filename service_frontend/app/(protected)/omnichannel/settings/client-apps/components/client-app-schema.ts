import { z } from 'zod';

export const clientAppSchema = z.object({
  name: z.string().trim().min(1, 'Name is required').max(120, 'Name is too long'),
});

export type ClientAppFormValues = z.infer<typeof clientAppSchema>;

export function defaultClientAppFormValues(name = ''): ClientAppFormValues {
  return { name };
}
