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
 * website cap of 2 is structural (only website1/website2 exist - no UI to add a
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

/**
 * Widget tab (plan 34 / A7b, AC-WEB-04) - appearance + greetings + pre-chat
 * toggles for a `WEBCHAT` channel. Every field optional so the schema stays
 * silent for every other channel type (same convention as the profile tab's
 * WhatsApp-only fields).
 */
export const channelWidgetSchema = z.object({
  widgetAccentColor: z
    .string()
    .trim()
    .regex(/^#[0-9a-fA-F]{6}$/, 'Enter a valid hex color (e.g. #FF5A00)')
    .optional(),
  widgetPosition: z.enum(['left', 'right']).optional(),
  widgetHeaderTitle: z.string().trim().max(80, 'Header title is too long').optional(),
  widgetAgentDisplayName: z.string().trim().max(80, 'Display name is too long').optional(),
  widgetGreeting: z.string().trim().max(500, 'Greeting is too long').optional(),
  widgetOfflineGreeting: z.string().trim().max(500, 'Offline greeting is too long').optional(),
  widgetAskName: z.boolean().optional(),
  widgetAskEmail: z.boolean().optional(),
  widgetAskPhone: z.boolean().optional(),
});

export type ChannelWidgetValues = z.infer<typeof channelWidgetSchema>;

/** One form drives every tab (single global Edit toggle + one Save, GP-1). */
export const channelDetailSchema = channelFormSchema.merge(channelProfileSchema).merge(channelWidgetSchema);
export type ChannelDetailValues = z.infer<typeof channelDetailSchema>;
