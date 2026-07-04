/**
 * Real account service — PATCH /me/profile (perm-free self-scope). Bound in
 * Phase B (one-line swap in account-service.ts).
 */
import { apiFetch } from '@/lib/api-client';
import type { AccountService, ProfileUpdate } from './account-service';

export const realAccountService: AccountService = {
  updateProfile(input: ProfileUpdate) {
    return apiFetch<ProfileUpdate>('/me/profile', {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },
};
