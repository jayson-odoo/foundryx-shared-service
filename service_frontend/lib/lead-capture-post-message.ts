/**
 * The hosted wizard's ONE way to talk to the product that opened it
 * (plan 64 AC-64-08): `{type: "lead-capture:done" | "lead-capture:closed",
 * sourceId?}` posted to `window.opener` with `targetOrigin` = the session's
 * `returnOrigin` ONLY - never `*`. No origin (a staff session opened in a
 * tab) = nothing is posted.
 */
import type { LeadCaptureMessage } from '@/types/lead-capture-wizard';

/** A bare `scheme://host[:port]` origin, or null. */
export function exactOrigin(value: string | null | undefined): string | null {
  if (!value || value === '*' || value === 'null') return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
    return url.origin === value.replace(/\/$/, '') ? url.origin : null;
  } catch {
    return null;
  }
}

export interface OpenerLike {
  postMessage: (message: unknown, targetOrigin: string) => void;
  closed?: boolean;
}

/** Post `message` to the opener at `returnOrigin`. True when posted. */
export function postToOpener(
  opener: OpenerLike | null | undefined,
  returnOrigin: string | null | undefined,
  message: LeadCaptureMessage,
): boolean {
  const origin = exactOrigin(returnOrigin);
  if (!opener || opener.closed || !origin) return false;
  try {
    opener.postMessage(message, origin);
    return true;
  } catch {
    return false;
  }
}
