/**
 * The new broadcast's red action under the Foundryx UIUX switch (playbook
 * 0.71.0 "Actions"): what it says, what blocks it and what it pulses, plus the
 * schedule's date + time split. Pure, so both are tested without a screen.
 *
 * The blocked state is derived from the SAME `broadcastFormSchema` the
 * switch-off form uses to grey its Send button, so the two looks can never
 * disagree on when a broadcast may go out.
 */
import { utcToZonedInputValue, zonedTimeToUtc } from '@/lib/datetime';
import type { FxBlocked } from '@/components/fx/actions/page-actions-context';
import {
  broadcastFormSchema,
  type BroadcastFormValues,
} from './broadcast-schema';

/** `data-fx-pulse-target` names of the fields the red action can wait for. */
export const BC_PULSE = {
  name: 'bc-name',
  audience: 'bc-audience',
  channel: 'bc-channel',
  template: 'bc-template',
  bindings: 'bc-bindings',
  date: 'bc-date',
  time: 'bc-time',
} as const;

/** "1 contact", "23 contacts". */
export function contactsCount(n: number): string {
  return `${n.toLocaleString('en-US')} ${n === 1 ? 'contact' : 'contacts'}`;
}

/** The time list: every half hour of the day, as "HH:MM". */
export const HALF_HOURS: string[] = Array.from(
  { length: 48 },
  (_, i) =>
    `${String(Math.floor(i / 2)).padStart(2, '0')}:${i % 2 ? '30' : '00'}`,
);

/** "14:30" -> "2:30 pm" (12-hour clock). */
export function fxClockLabel(hhmm: string): string {
  const m = hhmm.match(/^(\d{2}):(\d{2})$/);
  if (!m) return hhmm;
  const h = Number(m[1]);
  return `${h % 12 === 0 ? 12 : h % 12}:${m[2]} ${h < 12 ? 'am' : 'pm'}`;
}

/** The time list's options, keeping a saved time that is not on the half hour. */
export function timeOptions(
  current: string | null,
): { label: string; value: string }[] {
  const values =
    current && !HALF_HOURS.includes(current)
      ? [...HALF_HOURS, current].sort()
      : HALF_HOURS;
  return values.map((value) => ({ label: fxClockLabel(value), value }));
}

export interface ScheduleParts {
  /** Calendar day "2026-11-20" in the viewer's zone, or null. */
  date: string | null;
  /** Wall-clock "14:30" in the viewer's zone, or null. */
  time: string | null;
}

/** A stored instant -> the day and time a person picked, in `timeZone`. */
export function splitScheduledAt(
  iso: string | null,
  timeZone: string,
): ScheduleParts {
  const local = utcToZonedInputValue(iso, timeZone);
  if (!local) return { date: null, time: null };
  const [date, time] = local.split('T');
  return { date, time };
}

/** The day and time a person picked, in `timeZone` -> the instant sent to the
 *  backend. The same conversion the switch-off `datetime-local` field uses,
 *  so the same pick sends the same `scheduledAt`. */
export function joinScheduledAt(
  parts: ScheduleParts,
  timeZone: string,
): string | null {
  if (!parts.date || !parts.time) return null;
  const utc = zonedTimeToUtc(`${parts.date}T${parts.time}`, timeZone);
  return utc ? utc.toISOString() : null;
}

/**
 * Why the broadcast cannot go out yet, in the order the form reads (Details,
 * Audience, Channel, Message, Schedule), with the field to pulse. Undefined
 * when it can go.
 */
export function broadcastBlocked(
  values: BroadcastFormValues,
  schedule: ScheduleParts,
): FxBlocked | undefined {
  const parsed = broadcastFormSchema.safeParse(values);
  if (parsed.success) return undefined;
  const failed = new Set(
    parsed.error.issues.map((issue) => String(issue.path[0] ?? '')),
  );
  if (failed.has('name')) {
    return values.name.trim()
      ? {
          reason: 'Shorten the name to 200 characters.',
          pulseTarget: BC_PULSE.name,
        }
      : { reason: 'Name the broadcast.', pulseTarget: BC_PULSE.name };
  }
  if (failed.has('audience'))
    return { reason: 'Pick who gets it.', pulseTarget: BC_PULSE.audience };
  if (failed.has('channelId'))
    return { reason: 'Pick a channel.', pulseTarget: BC_PULSE.channel };
  if (failed.has('templateId'))
    return { reason: 'Pick a template.', pulseTarget: BC_PULSE.template };
  if (failed.has('bindings'))
    return {
      reason: 'Fill in every template value.',
      pulseTarget: BC_PULSE.bindings,
    };
  if (failed.has('scheduledAt')) {
    if (!schedule.date)
      return { reason: 'Pick a date to send.', pulseTarget: BC_PULSE.date };
    if (!schedule.time)
      return { reason: 'Pick a time to send.', pulseTarget: BC_PULSE.time };
    return { reason: 'Pick a time in the future.', pulseTarget: BC_PULSE.time };
  }
  if (failed.has('labels'))
    return { reason: 'Remove the empty label.', pulseTarget: BC_PULSE.name };
  return { reason: 'Fix the highlighted fields.' };
}

/** The red action's short and full labels ("Send now to 23 contacts with
 *  promo_nov_2026"). The full label needs the count and the template; the
 *  schedule's also needs the time. */
export function broadcastMainLabels(input: {
  mode: BroadcastFormValues['scheduleMode'];
  audienceCount: number | null;
  templateName: string;
  /** "20 Nov 2026, 2:30 pm", or '' when no time is picked. */
  when: string;
}): { label: string; fullLabel?: string } {
  const { mode, audienceCount, templateName, when } = input;
  const known = audienceCount !== null && Boolean(templateName);
  if (mode === 'now') {
    return {
      label: 'Send now',
      fullLabel: known
        ? `Send now to ${contactsCount(audienceCount as number)} with ${templateName}`
        : undefined,
    };
  }
  return {
    label: 'Schedule broadcast',
    fullLabel:
      known && when
        ? `Schedule ${templateName} to ${contactsCount(audienceCount as number)} for ${when}`
        : undefined,
  };
}
