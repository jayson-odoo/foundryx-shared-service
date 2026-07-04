/**
 * Phone-number helpers (E.164). Shared by the channel onboarding flow now, and
 * reusable by contacts/manual channel entry later.
 *
 * E.164: optional leading '+', country code starting 1-9, then up to 14 more
 * digits (max 15 total). Common separators (spaces, dashes, parens) are allowed
 * in input and stripped before validation/normalisation.
 */

/** Strip everything except digits and a single leading '+'. */
export function normalizePhone(input: string): string {
  const trimmed = input.trim();
  const hasPlus = trimmed.startsWith('+');
  const digits = trimmed.replace(/\D/g, '');
  return hasPlus ? `+${digits}` : digits;
}

/** True if `input` is a plausible E.164 phone number (8–15 digits). */
export function isValidPhone(input: string): boolean {
  const normalized = normalizePhone(input);
  return /^\+?[1-9]\d{7,14}$/.test(normalized);
}
