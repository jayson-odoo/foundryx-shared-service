/**
 * Mock close-reason service (S0, plan 27). In-memory store seeded with the
 * respond.io default set (§5.5): General Inquiry, Sales Inquiry, Payment
 * Issue, Others - all editable/deletable, `usesCount` pre-seeded on two rows
 * so the list demonstrates BOTH the Delete and the Deactivate/Activate row
 * actions (AC-IVE-26).
 *
 * Single-workspace mock (same convention as `contact-tag-service.mock.ts`):
 * `workspaceId` is accepted + stamped but not filtered on - the real workspace
 * id varies per environment, the mock always serves the one seeded set.
 */
import { ApiError } from '@/lib/api-client';
import type { CloseReason, CreateCloseReasonInput, UpdateCloseReasonInput } from '@/types/omnichannel';
import type { CloseReasonService } from './close-reason-service';
import { delay } from './mock-query';

const MAX_REASONS = 100;
const SEED_WORKSPACE_ID = 'wsp-001';

let idSeq = 1;
const nextId = () => `cr-${idSeq++}`;
const iso = (daysAgo: number) => new Date(Date.now() - daysAgo * 86_400_000).toISOString();

function seed(): CloseReason[] {
  idSeq = 1;
  return [
    { id: nextId(), workspaceId: SEED_WORKSPACE_ID, name: 'General Inquiry', sortOrder: 0, isActive: true, usesCount: 3, createdAt: iso(90) },
    { id: nextId(), workspaceId: SEED_WORKSPACE_ID, name: 'Sales Inquiry', sortOrder: 1, isActive: true, usesCount: 1, createdAt: iso(90) },
    { id: nextId(), workspaceId: SEED_WORKSPACE_ID, name: 'Payment Issue', sortOrder: 2, isActive: true, usesCount: 0, createdAt: iso(90) },
    { id: nextId(), workspaceId: SEED_WORKSPACE_ID, name: 'Others', sortOrder: 3, isActive: true, usesCount: 0, createdAt: iso(90) },
  ];
}

let reasons: CloseReason[] = seed();

/** Reset mock state between tests / a fresh browser session. */
export function __mockResetCloseReasons(): void {
  reasons = seed();
}

/** Cross-mock read used by `conversation-service.mock.ts` (Close dialog +
 *  events feed resolve `closeReasonName` the same way the real backend
 *  would). `workspaceId` accepted, not filtered (S0 single-workspace mock). */
export function __mockAllCloseReasons(_workspaceId: string): CloseReason[] {
  void _workspaceId;
  return [...reasons];
}

/** Cross-mock write - `conversation-service.mock.ts closeThread` bumps the
 *  chosen reason's `usesCount` so Deactivate-vs-Delete stays honest after a
 *  close in the same session. */
export function __mockBumpCloseReasonUse(id: string): void {
  reasons = reasons.map((r) => (r.id === id ? { ...r, usesCount: r.usesCount + 1 } : r));
}

function validateName(name: string, excludingId?: string): string | null {
  if (!name.trim()) return 'Name is required.';
  if (name.length > 200) return 'Name must be 200 characters or fewer.';
  const dup = reasons.some(
    (r) => r.id !== excludingId && r.name.trim().toLowerCase() === name.trim().toLowerCase(),
  );
  if (dup) return 'A close reason with this name already exists.';
  return null;
}

function fieldErrorsError(message: string, fieldErrors: Record<string, string>): ApiError {
  return new ApiError(message, 422, null, { fieldErrors });
}

export const mockCloseReasonService: CloseReasonService = {
  async list(workspaceId) {
    void workspaceId;
    return delay([...reasons].sort((a, b) => a.sortOrder - b.sortOrder));
  },

  async create(workspaceId, input: CreateCloseReasonInput) {
    const nameError = validateName(input.name);
    if (nameError) throw fieldErrorsError(nameError, { name: nameError });
    if (reasons.length >= MAX_REASONS) {
      throw new ApiError(`A workspace may have at most ${MAX_REASONS} close reasons.`, 422);
    }
    const created: CloseReason = {
      id: nextId(),
      workspaceId,
      name: input.name.trim(),
      sortOrder: input.sortOrder ?? reasons.length,
      isActive: input.isActive ?? true,
      usesCount: 0,
      createdAt: new Date().toISOString(),
    };
    reasons = [...reasons, created];
    return delay(created);
  },

  async update(workspaceId, id, input: UpdateCloseReasonInput) {
    void workspaceId;
    const existing = reasons.find((r) => r.id === id);
    if (!existing) throw new ApiError('Close reason not found.', 404);
    if (input.name !== undefined) {
      const nameError = validateName(input.name, id);
      if (nameError) throw fieldErrorsError(nameError, { name: nameError });
    }
    const updated: CloseReason = {
      ...existing,
      name: input.name !== undefined ? input.name.trim() : existing.name,
      sortOrder: input.sortOrder ?? existing.sortOrder,
      isActive: input.isActive ?? existing.isActive,
    };
    reasons = reasons.map((r) => (r.id === id ? updated : r));
    return delay(updated);
  },

  async remove(workspaceId, id) {
    void workspaceId;
    const existing = reasons.find((r) => r.id === id);
    if (!existing) throw new ApiError('Close reason not found.', 404);
    if (existing.usesCount > 0) {
      throw new ApiError(
        'This close reason has been used to close a conversation - deactivate it instead.',
        409,
        null,
        { code: 'close_reason_in_use' },
      );
    }
    reasons = reasons.filter((r) => r.id !== id);
    await delay(undefined);
  },
};
