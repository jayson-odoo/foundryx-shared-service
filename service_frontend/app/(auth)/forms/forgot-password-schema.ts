import { z } from 'zod';

export const getForgotPasswordSchema = () => {
  return z.object({
    email: z
      .string()
      .email({ message: 'Please enter a valid email address.' })
      .min(1, { message: 'Email is required.' }),
  });
};

export type ForgotPasswordSchemaType = z.infer<
  ReturnType<typeof getForgotPasswordSchema>
>;
