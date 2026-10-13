import { z } from 'zod';

// No `status` field (issue #94, ideation round 2, AC-94-33/34) - the form
// never shows or moves status in any mode (owner Q5); status lives on the
// list/board and changes only through the status_engine actions.
//
// Plan 20 (owner ruling 13 Oct): the card fields are Title, Business problem
// (the `problem` column), Desired outcome, Use cases and Current workaround.
// Proposed solution / Impact / Department are no longer edited here (their
// data is kept server-side; the form simply never sends them).
export const ideaFormSchema = z.object({
  problem: z.string().trim().min(1, 'A business problem is required.'),
  productId: z.string().min(1, 'Select a product.'),
  // Plain (not .optional().default()) so the zod input and output types match -
  // a divergent pair breaks the useForm<>/zodResolver generic. Empty is allowed
  // (no min); toFormValues always seeds ''/[] so the fields are never undefined.
  title: z.string(),
  desiredOutcome: z.string(),
  useCases: z.array(z.string()),
  currentWorkaround: z.string(),
  rawText: z.string(),
});

export type IdeaFormValues = z.infer<typeof ideaFormSchema>;
