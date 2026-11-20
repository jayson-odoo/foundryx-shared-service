/**
 * Mock business hours service (plan 31 S6). Single-workspace in-memory store
 * (same convention as `close-reason-service.mock.ts`) - `workspaceId` is
 * accepted but not filtered on. Starts UNCONFIGURED (`timezone: null`, every
 * day empty) exactly like a fresh `omnichannel_settings` row, so the tab's
 * empty/missing-prerequisite state is exercised without extra setup.
 */
import { ApiError } from '@/lib/api-client';
import {
  BUSINESS_HOURS_WEEKDAYS,
  type BusinessHours,
  type BusinessHoursWindows,
  type UpdateBusinessHoursInput,
} from '@/types/omnichannel';
import type { BusinessHoursService } from './business-hours-service';
import { delay } from './mock-query';

const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/;

function emptyWindows(): BusinessHoursWindows {
  const result = {} as BusinessHoursWindows;
  for (const day of BUSINESS_HOURS_WEEKDAYS) result[day] = [];
  return result;
}

let state: BusinessHours = {
  workspaceId: '',
  timezone: null,
  windows: emptyWindows(),
};

/** Reset mock state between tests / a fresh browser session. */
export function __mockResetBusinessHours(): void {
  state = { workspaceId: '', timezone: null, windows: emptyWindows() };
}

function validate(input: UpdateBusinessHoursInput): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!input.timezone.trim()) errors.timezone = 'Choose a timezone.';
  for (const day of BUSINESS_HOURS_WEEKDAYS) {
    const rows = input.windows[day] ?? [];
    rows.forEach((row, idx) => {
      const key = `windows.${day}.${idx}`;
      if (TIME_RE.test(row.from) === false || TIME_RE.test(row.to) === false) {
        errors[key] = 'Times must be HH:MM (24-hour).';
      } else if (row.from === row.to) {
        errors[key] = 'End time must differ from the start time.';
      }
    });
  }
  return errors;
}

export const mockBusinessHoursService: BusinessHoursService = {
  async get(workspaceId) {
    return delay({ ...state, workspaceId });
  },

  async update(workspaceId, input: UpdateBusinessHoursInput) {
    const errors = validate(input);
    if (Object.keys(errors).length) {
      throw new ApiError('Business hours validation failed', 422, null, { fieldErrors: errors });
    }
    state = { workspaceId, timezone: input.timezone, windows: input.windows };
    return delay({ ...state });
  },
};
