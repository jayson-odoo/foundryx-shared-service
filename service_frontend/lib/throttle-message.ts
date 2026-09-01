/**
 * User-facing message for a 429 throttle response (plan 10 §5) - distinct from
 * the uniform invalid-credentials error by design.
 */
export function throttleMessage(retryAfterSeconds: number | null): string {
  if (retryAfterSeconds == null || retryAfterSeconds <= 0) {
    return 'Too many attempts - please try again in a few minutes.';
  }
  const minutes = Math.max(1, Math.ceil(retryAfterSeconds / 60));
  return `Too many attempts - please try again in ~${minutes} minute${minutes === 1 ? '' : 's'}.`;
}
