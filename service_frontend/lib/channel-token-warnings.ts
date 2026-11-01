/**
 * Warnings shown after a WhatsApp token is saved (plan 42): used by the Replace
 * token dialog and the manual connect result, so both read the same way.
 */
export interface TokenWarningInput {
  /** Meta's answer to the webhook renewal; null when the channel has no WABA id. Omit on connect. */
  subscribed?: boolean | null;
  /** When the token stops working; null or omitted when it never expires or is unreadable. */
  tokenExpiresAt?: string | null;
}

export const WEBHOOK_WARNING =
  'The webhook subscription could not be confirmed, so messages may not arrive yet.';

export function expiryWarning(tokenExpiresAt: string, formatDate: (iso: string) => string): string {
  return `This token expires on ${formatDate(tokenExpiresAt)}.`;
}

export function tokenWarnings(
  input: TokenWarningInput,
  formatDate: (iso: string) => string,
): string[] {
  const out: string[] = [];
  if (input.subscribed === false || input.subscribed === null) out.push(WEBHOOK_WARNING);
  if (input.tokenExpiresAt) out.push(expiryWarning(input.tokenExpiresAt, formatDate));
  return out;
}
