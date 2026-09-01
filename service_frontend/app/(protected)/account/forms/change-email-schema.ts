import { z } from 'zod';

/**
 * Change-email request form (plan sprint-2/04). Password is re-entered as
 * fresh proof of possession - its STRENGTH is not validated here (it's the
 * existing password, not a new one).
 */
export const getChangeEmailSchema = () => {
  return z.object({
    newEmail: z
      .string()
      .min(1, { message: 'New email is required.' })
      .email({ message: 'Please enter a valid email address.' }),
    password: z.string().min(1, { message: 'Current password is required.' }),
  });
};

export type ChangeEmailSchemaType = z.infer<ReturnType<typeof getChangeEmailSchema>>;
