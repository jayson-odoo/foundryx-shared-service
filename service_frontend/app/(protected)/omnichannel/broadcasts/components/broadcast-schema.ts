import { z } from 'zod';
import type { FilterGroup } from '@/types/resource';

/** One WhatsApp template parameter slot binding (D-A4-4/D-A4-5) - `static`
 *  text may never carry token syntax (anti-SSTI guard, save-time), a
 *  `contactField` binding always requires a non-empty fallback. */
export const templateBindingSchema = z.discriminatedUnion('source', [
  z.object({
    source: z.literal('static'),
    text: z
      .string()
      .refine((v) => !/\{\{|\}\}/.test(v), 'Static text cannot contain template token syntax.'),
  }),
  z.object({
    source: z.literal('contactField'),
    field: z.string().min(1, 'Choose a contact field.'),
    fallback: z.string().trim().min(1, 'A fallback value is required.'),
  }),
]);

const isFilterGroup = (v: unknown): v is FilterGroup =>
  typeof v === 'object' && v !== null && (v as { kind?: unknown }).kind === 'group';

/** Exactly one of segment | filter | contacts (AC-BRD-18). The three unused
 *  branches arrive as `null` on the real wire (`BroadcastAudienceOut` always
 *  emits all four keys) - `.nullable()` alongside `.optional()` so a saved
 *  broadcast loaded back into the builder validates (plan 29 S4). */
export const broadcastAudienceSchema = z
  .object({
    kind: z.enum(['segment', 'filter', 'contacts']),
    segmentId: z.string().nullable().optional(),
    segmentName: z.string().nullable().optional(),
    filter: z.custom<FilterGroup>(isFilterGroup).nullable().optional(),
    contactIds: z.array(z.string()).nullable().optional(),
  })
  .superRefine((value, ctx) => {
    const has = {
      segment: !!value.segmentId,
      filter: !!value.filter && value.filter.rules.length > 0,
      contacts: !!value.contactIds && value.contactIds.length > 0,
    };
    const count = Object.values(has).filter(Boolean).length;
    if (count !== 1) {
      ctx.addIssue({ code: 'custom', message: 'Choose exactly one audience source.', path: ['kind'] });
      return;
    }
    if (value.kind === 'segment' && !has.segment) {
      ctx.addIssue({ code: 'custom', message: 'Choose a saved segment.', path: ['segmentId'] });
    }
    if (value.kind === 'filter' && !has.filter) {
      ctx.addIssue({ code: 'custom', message: 'Add at least one filter condition.', path: ['filter'] });
    }
    if (value.kind === 'contacts' && !has.contacts) {
      ctx.addIssue({ code: 'custom', message: 'Select at least one contact.', path: ['contactIds'] });
    }
  });

export const broadcastFormSchema = z
  .object({
    name: z.string().trim().min(1, 'Name is required.').max(200, 'Name is too long (max 200 characters).'),
    labels: z.array(z.string().trim().min(1)),
    channelId: z.string().min(1, 'Choose a channel.'),
    audience: broadcastAudienceSchema,
    templateId: z.string().min(1, 'Choose a template.'),
    bindings: z.object({
      header: z.array(templateBindingSchema),
      body: z.array(templateBindingSchema),
      buttons: z.array(templateBindingSchema),
    }),
    scheduleMode: z.enum(['now', 'schedule']),
    scheduledAt: z.string().nullable(),
  })
  .superRefine((value, ctx) => {
    if (value.scheduleMode === 'schedule') {
      if (!value.scheduledAt) {
        ctx.addIssue({ code: 'custom', message: 'Choose a date and time.', path: ['scheduledAt'] });
      } else if (new Date(value.scheduledAt).getTime() <= Date.now()) {
        ctx.addIssue({ code: 'custom', message: 'Schedule a time in the future.', path: ['scheduledAt'] });
      }
    }
  });

export type BroadcastFormValues = z.infer<typeof broadcastFormSchema>;

export const EMPTY_BROADCAST_FORM_VALUES: BroadcastFormValues = {
  name: '',
  labels: [],
  channelId: '',
  audience: { kind: 'segment' },
  templateId: '',
  bindings: { header: [], body: [], buttons: [] },
  scheduleMode: 'now',
  scheduledAt: null,
};
