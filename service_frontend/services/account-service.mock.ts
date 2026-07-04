/**
 * Mock account service (Phase A) — echoes the update after a short latency.
 * Failure knob: name `Fail Save` rejects (server-error state).
 */
import type { AccountService } from './account-service';
import { delay } from './mock-query';

export const mockAccountService: AccountService = {
  async updateProfile(input) {
    if (input.name === 'Fail Save') {
      throw new Error('The server rejected the change. Please try again.');
    }
    return delay({ ...input });
  },
};
