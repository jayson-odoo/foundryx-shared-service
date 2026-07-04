/**
 * Account profile service (plan sprint-2/06) — self-service edits on the My
 * Account Resource form. Phase A binds the mock; Phase B swaps to the real
 * api-client impl in ONE line (bottom). The interface IS the backend
 * contract: `PATCH /me/profile` (perm-free self-scope, like /me/preferences —
 * name only; email rides the plan-04 ceremony, never this).
 */
import { realAccountService } from './account-service.real';

export interface ProfileUpdate {
  name: string;
}

export interface AccountService {
  /** Update own profile fields. Returns the fresh values. */
  updateProfile(input: ProfileUpdate): Promise<ProfileUpdate>;
}

// Phase B swap done — mock retained in account-service.mock.ts for tests.
export const accountService: AccountService = realAccountService;
