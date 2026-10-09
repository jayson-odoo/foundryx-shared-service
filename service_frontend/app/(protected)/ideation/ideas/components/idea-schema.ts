import { z } from 'zod';

// No `status` field (issue #94, ideation round 2, AC-94-33/34) - the form
// never shows or moves status in any mode (owner Q5); status lives on the
// list/board and changes only through the status_engine actions.
export const ideaFormSchema = z.object({
  problem: z.string().trim().min(1, 'A problem statement is required.'),
  productId: z.string().min(1, 'Select a product.'),
  // Plain (not .optional().default()) so the zod input and output types match -
  // a divergent pair breaks the useForm<>/zodResolver generic. Empty is allowed
  // (no min); toFormValues always seeds '' so the fields are never undefined.
  proposedSolution: z.string(),
  impact: z.string(),
  department: z.string(),
  rawText: z.string(),
});

export type IdeaFormValues = z.infer<typeof ideaFormSchema>;
