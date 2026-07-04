/**
 * Account self-service types (plan sprint-2/04) — the change-email ceremony.
 *
 * Dual confirmation: the OLD mailbox approves the change, the NEW mailbox
 * verifies deliverability; the email flips only after the new-side verify.
 */

/** Server-side lifecycle of a change request (terminal states never reach the UI list). */
export type EmailChangeStatus = 'PENDING_OLD' | 'PENDING_NEW';

/** The caller's outstanding change request (at most one — re-request cancels prior). */
export interface PendingEmailChange {
  /** The address the account will move to once verified. */
  newEmail: string;
  status: EmailChangeStatus;
  /** ISO 8601 UTC — whole request expires. */
  expiresAt: string;
  createdAt: string;
}
