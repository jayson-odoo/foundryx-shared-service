import { z } from 'zod';
import { getPasswordSchema } from '@/app/(auth)/forms/password-schema';

/** Portal forgot-password request. */
export const getPortalForgotPasswordSchema = () =>
  z.object({
    email: z
      .string()
      .email({ message: 'Please enter a valid email address.' })
      .min(1, { message: 'Email is required.' }),
  });

export type PortalForgotPasswordSchemaType = z.infer<
  ReturnType<typeof getPortalForgotPasswordSchema>
>;

/** Portal set/change-password — reuses the shared password policy mirror. */
export const getPortalChangePasswordSchema = () =>
  z
    .object({
      newPassword: getPasswordSchema(),
      confirmPassword: z.string(),
    })
    .refine((data) => data.newPassword === data.confirmPassword, {
      message: 'Passwords do not match.',
      path: ['confirmPassword'],
    });

export type PortalChangePasswordSchemaType = z.infer<
  ReturnType<typeof getPortalChangePasswordSchema>
>;
