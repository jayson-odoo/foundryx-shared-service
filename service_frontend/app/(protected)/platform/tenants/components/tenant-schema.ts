import { z } from 'zod';
import { getPasswordSchema } from '@/app/(auth)/forms/password-schema';
import { isReservedTenantSlug, isValidTenantSlug } from '@/lib/tenant';

/**
 * Validation for the tenant form (plan 07 §4, §7). One value shape for both
 * modes; the provision schema additionally requires the first-admin block.
 * Slug is immutable after creation — the update schema ignores it.
 */

const emptyOrEmail = z
  .string()
  .trim()
  .max(254, 'Email is too long.')
  .refine((v) => v === '' || z.string().email().safeParse(v).success, 'Enter a valid email.');

const baseFields = {
  name: z.string().trim().min(1, 'Name is required.').max(120, 'Name is too long.'),
  contactName: z.string().trim().max(120, 'Contact name is too long.'),
  contactEmail: emptyOrEmail,
  customDomain: z.string().trim().max(253, 'Domain is too long.'),
  notes: z.string().trim().max(2000, 'Notes are too long.'),
  // First admin block — required on create only (provision schema below).
  adminName: z.string().trim().max(120, 'Name is too long.'),
  adminEmail: emptyOrEmail,
  adminPassword: z.string().max(72, 'Password is too long.'), // bcrypt 72-byte cap
};

export const tenantSlugSchema = z
  .string()
  .trim()
  .min(1, 'Slug is required.')
  .refine(isValidTenantSlug, 'Lowercase letters/numbers with single hyphens, 3–63 chars.')
  .refine((s) => !isReservedTenantSlug(s), 'This slug is reserved.');

/** Edit mode — slug read-only (validated at create, immutable after). */
export const tenantUpdateSchema = z.object({ ...baseFields, slug: z.string() });

/** Create mode — slug rules enforced + first admin required (plan 07 §7). */
export const tenantProvisionSchema = z.object({
  ...baseFields,
  slug: tenantSlugSchema,
  adminName: baseFields.adminName.refine((v) => v.length > 0, 'Admin name is required.'),
  adminEmail: z.string().trim().email('Enter a valid email.').max(254),
  // Same policy as set-password/signup (plan 10) — the operator-set temp
  // password is live immediately, so it gets no weaker rules. Backend mirrors
  // this in TenantProvisionRequest.
  adminPassword: getPasswordSchema().max(72, 'Password is too long.'),
});

export type TenantFormValues = z.infer<typeof tenantUpdateSchema>;
