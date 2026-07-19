import { z } from 'zod';
import type { IdeaStatus } from '@/types/ideation';

export const ideaFormSchema = z.object({
  problem: z.string().trim().min(1, 'A problem statement is required.'),
  productId: z.string().min(1, 'Select a product.'),
  status: z.custom<IdeaStatus>(),
  // Plain (not .optional().default()) so the zod input and output types match —
  // a divergent pair breaks the useForm<>/zodResolver generic. Empty is allowed
  // (no min); toFormValues always seeds '' so the fields are never undefined.
  proposedSolution: z.string(),
  impact: z.string(),
  department: z.string(),
  rawText: z.string(),
});

export type IdeaFormValues = z.infer<typeof ideaFormSchema>;
