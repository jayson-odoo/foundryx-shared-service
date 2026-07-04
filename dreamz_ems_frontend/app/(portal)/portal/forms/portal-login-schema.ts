import { z } from 'zod';

/** Password login (primary). */
export const getPortalLoginSchema = () =>
  z.object({
    email: z
      .string()
      .email({ message: 'Please enter a valid email address.' })
      .min(1, { message: 'Email is required.' }),
    password: z.string().min(1, { message: 'Password is required.' }),
    rememberMe: z.boolean().optional(),
  });

export type PortalLoginSchemaType = z.infer<
  ReturnType<typeof getPortalLoginSchema>
>;

/** OTP step 1 — request a code by email. */
export const getPortalOtpEmailSchema = () =>
  z.object({
    email: z
      .string()
      .email({ message: 'Please enter a valid email address.' })
      .min(1, { message: 'Email is required.' }),
    rememberMe: z.boolean().optional(),
  });

export type PortalOtpEmailSchemaType = z.infer<
  ReturnType<typeof getPortalOtpEmailSchema>
>;

/** OTP step 2 — enter the 6-digit code. */
export const getPortalOtpCodeSchema = () =>
  z.object({
    code: z
      .string()
      .min(6, { message: 'Enter the 6-digit code.' })
      .max(6, { message: 'Enter the 6-digit code.' })
      .regex(/^\d{6}$/, { message: 'Enter the 6-digit code.' }),
  });

export type PortalOtpCodeSchemaType = z.infer<
  ReturnType<typeof getPortalOtpCodeSchema>
>;
