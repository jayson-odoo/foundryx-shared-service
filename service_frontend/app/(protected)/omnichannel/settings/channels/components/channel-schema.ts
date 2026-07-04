import { z } from 'zod';
import { WHATSAPP_VERTICAL_SET } from '@/lib/whatsapp-verticals';

/** Editable channel fields (most channel data is Meta-owned + read-only). */
export const channelFormSchema = z.object({
  name: z.string().trim().min(1, 'Name is required').max(80, 'Name is too long'),
  isActive: z.boolean(),
});

export type ChannelFormValues = z.infer<typeof channelFormSchema>;

const optionalUrl = z
  .string()
  .trim()
  .max(2048, 'URL is too long')
  .refine((v) => v === '' || /^https?:\/\//i.test(v), 'Enter a valid URL (http:// or https://)')
  .optional();

/**
 * Profile-tab form (mirrors the backend save-time validation, plan 06 §6). The
 * website cap of 2 is structural (only website1/website2 exist — no UI to add a
 * third), satisfying BR-8.
 */
export const channelProfileSchema = z.object({
  about: z.string().trim().max(512, 'About is too long').optional(),
  address: z.string().trim().max(256, 'Address is too long').optional(),
  description: z.string().trim().max(512, 'Description is too long').optional(),
  email: z
    .string()
    .trim()
    .refine((v) => v === '' || /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v), 'Enter a valid email address')
    .optional(),
  vertical: z
    .string()
    .refine((v) => v === '' || WHATSAPP_VERTICAL_SET.has(v), 'Pick a valid vertical')
    .optional(),
  website1: optionalUrl,
  website2: optionalUrl,
});

export type ChannelProfileValues = z.infer<typeof channelProfileSchema>;

/** One form drives both tabs (single global Edit toggle + one Save, GP-1). */
export const channelDetailSchema = channelFormSchema.merge(channelProfileSchema);
export type ChannelDetailValues = z.infer<typeof channelDetailSchema>;
