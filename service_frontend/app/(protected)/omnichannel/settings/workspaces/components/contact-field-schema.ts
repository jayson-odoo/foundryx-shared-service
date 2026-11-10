import { z } from 'zod';
import { RESERVED_CONTACT_FIELD_KEYS } from '@/types/omnichannel';
import type { ContactFieldType, ContactFieldVisibility } from '@/types/omnichannel';

/** The 8 field types (UAC Definitions), SearchSelect options for the dialog. */
export const CONTACT_FIELD_TYPE_OPTIONS: { value: ContactFieldType; label: string }[] = [
  { value: 'text', label: 'Text' },
  { value: 'list', label: 'Dropdown list' },
  { value: 'checkbox', label: 'Checkbox' },
  { value: 'email', label: 'Email' },
  { value: 'number', label: 'Number' },
  { value: 'url', label: 'URL' },
  { value: 'date', label: 'Date' },
  { value: 'time', label: 'Time' },
];

export const CONTACT_FIELD_VISIBILITY_OPTIONS: { value: ContactFieldVisibility; label: string }[] = [
  { value: 'always', label: 'Always shown' },
  { value: 'hidden', label: 'Hidden from the contact panel' },
];

const KEY_RE = /^[a-z][a-zA-Z0-9_]{0,39}$/;

/**
 * Derive a valid Field ID from the label - camelCase, trimmed to the backend's
 * 40-char cap (AC-CDM-02). Best-effort: a label with no letters at all (rare)
 * yields '' and the user types the key by hand - the field stays editable
 * until save either way.
 */
export function slugifyFieldKey(label: string): string {
  const words = label
    .trim()
    .split(/[^a-zA-Z0-9]+/)
    .filter(Boolean);
  if (!words.length) return '';
  const [first, ...rest] = words;
  const firstWord = first.replace(/^[^a-zA-Z]+/, '');
  const key =
    firstWord.toLowerCase() +
    rest.map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join('');
  return key.slice(0, 40);
}

export const contactFieldSchema = z
  .object({
    label: z.string().trim().min(1, 'Name is required').max(80, 'Name is too long'),
    key: z
      .string()
      .trim()
      .min(1, 'Field ID is required')
      .regex(KEY_RE, 'Start with a lowercase letter; letters, numbers and underscore only.')
      .refine((v) => !RESERVED_CONTACT_FIELD_KEYS.includes(v), 'This ID is reserved for a system field.'),
    description: z.string().trim().max(500, 'Description is too long'),
    type: z.enum(['text', 'list', 'checkbox', 'email', 'number', 'url', 'date', 'time']),
    options: z.array(z.string()),
    visibility: z.enum(['always', 'hidden']),
  })
  .superRefine((values, ctx) => {
    if (values.type === 'list' && !values.options.some((o) => o.trim())) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['options'], message: 'Add at least one option.' });
    }
  });

export type ContactFieldFormValues = z.infer<typeof contactFieldSchema>;

export function defaultContactFieldFormValues(): ContactFieldFormValues {
  return { label: '', key: '', description: '', type: 'text', options: [], visibility: 'always' };
}
