/**
 * Words the broadcasts list and the broadcast page use under the Foundryx
 * UIUX switch (playbook 0.71.0 "When something is done", "The red action says
 * exactly what it will do"). Pure, so they are tested without a screen.
 */
import type { FxDoneInput } from '@/lib/toast';
import type { Broadcast } from '@/types/omnichannel';
import { contactsCount } from './fx-broadcast-actions';

const quoted = (name: string) => `“${name}”`;

function broadcastsCount(n: number): string {
  return `${n.toLocaleString('en-US')} ${n === 1 ? 'broadcast' : 'broadcasts'}`;
}

/** How many contacts the rows go to, once the backend has counted them. */
function recipientsOf(rows: Broadcast[]): string | undefined {
  const total = rows.reduce((sum, r) => sum + (r.counts?.total ?? 0), 0);
  return total > 0 ? `to ${contactsCount(total)}` : undefined;
}

/** After Send now: "“November promo” is sending", "to 23 contacts, by Kay". */
export function fxSendingToast(rows: Broadcast[], byWhom?: string): FxDoneInput {
  return {
    what: rows.length === 1 ? `${quoted(rows[0].name)} is sending` : `${broadcastsCount(rows.length)} are sending`,
    forWhom: recipientsOf(rows),
    byWhom,
  };
}

/** After Cancel: "“November promo” cancelled". */
export function fxCancelledToast(rows: Broadcast[], byWhom?: string): FxDoneInput {
  return {
    what: rows.length === 1 ? `${quoted(rows[0].name)} cancelled` : `${broadcastsCount(rows.length)} cancelled`,
    byWhom,
  };
}

/** After Duplicate: "“November promo” copied as “November promo (copy)”". */
export function fxDuplicatedToast(source: Broadcast, copy: Broadcast, byWhom?: string): FxDoneInput {
  return {
    what: `${quoted(source.name)} copied as ${quoted(copy.name)}`,
    byWhom,
  };
}

/**
 * The red action's full label for Send now on one broadcast: "Send now to 23
 * contacts with promo_nov_2026" once the recipients are counted, else "Send
 * November promo now with promo_nov_2026".
 */
export function fxSendNowLabel(rows: Broadcast[]): string {
  if (rows.length !== 1) return rows.length > 1 ? `Send ${broadcastsCount(rows.length)} now` : 'Send now';
  const row = rows[0];
  const total = row.counts?.total ?? 0;
  const tpl = row.templateName ? ` with ${row.templateName}` : '';
  return total > 0 ? `Send now to ${contactsCount(total)}${tpl}` : `Send ${row.name} now${tpl}`;
}
