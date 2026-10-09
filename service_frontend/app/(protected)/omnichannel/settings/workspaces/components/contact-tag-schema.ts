import { z } from 'zod';

export const contactTagSchema = z.object({
  name: z.string().trim().min(1, 'Name is required').max(60, 'Name is too long'),
  emoji: z.string().trim().max(8, 'Use a single emoji'),
  color: z.string().trim(),
  description: z.string().trim().max(500, 'Description is too long'),
});

export type ContactTagFormValues = z.infer<typeof contactTagSchema>;

export function defaultContactTagFormValues(): ContactTagFormValues {
  return { name: '', emoji: '', color: '#6B7280', description: '' };
}
