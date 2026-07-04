/**
 * Auth surface flags (plan 10 D3). Public self-signup is parked until real
 * tenant provisioning lands (BL-032) — a kill-switch, not a deletion: the
 * signin link hides and /signup + /verify-email render not-found while off.
 * Backend mirrors this with `signup_enabled` (endpoint 404s).
 */
export const signupEnabled =
  process.env.NEXT_PUBLIC_SIGNUP_ENABLED === 'true';
