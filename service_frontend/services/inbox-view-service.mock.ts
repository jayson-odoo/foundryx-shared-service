/**
 * Mock inbox-view service (S0, plan 27). In-memory store seeded with 4 saved
 * views spanning own/shared and a range of filter shapes, so the rail's Views
 * section + the save-view dialog are tunable with no backend.
 *
 * `ownerUserId`/`ownerName` mirror `MOCK_CURRENT_USER` in
 * `conversation-service.mock.ts` ('usr-demo' / 'Demo User') by literal value
 * (no cross-import - keeps the two mocks independent, same convention as
 * `contact-tag-service.mock.ts`). Single-workspace mock: `workspaceId` is
 * accepted + stamped but not filtered on.
 */
import { ApiError } from '@/lib/api-client';
import type { CreateInboxViewInput, InboxView, UpdateInboxViewInput } from '@/types/omnichannel';
import type { InboxViewService } from './inbox-view-service';
import { __mockAllContactTags } from './contact-tag-service.mock';
import { delay } from './mock-query';

/** Resolve the seed tag id by name (same convention as
 *  `conversation-service.mock.ts tagRef` - never hardcode the generated id). */
function tagId(name: string): string {
  const t = __mockAllContactTags('wsp-001').find((x) => x.name === name);
  return t?.id ?? name;
}

const MAX_VIEWS = 50;
const SEED_WORKSPACE_ID = 'wsp-001';
const CURRENT_USER = { id: 'usr-demo', name: 'Demo User' };
const OTHER_USER = { id: 'usr-amira', name: 'Amira Tan' };

let idSeq = 1;
const nextId = () => `view-${idSeq++}`;
const iso = (daysAgo: number) => new Date(Date.now() - daysAgo * 86_400_000).toISOString();

function seed(): InboxView[] {
  idSeq = 1;
  return [
    {
      id: nextId(),
      workspaceId: SEED_WORKSPACE_ID,
      name: 'My open, unreplied',
      ownerUserId: CURRENT_USER.id,
      ownerName: CURRENT_USER.name,
      isShared: false,
      filter: { statuses: ['OPEN'], assignee: 'me', unreplied: true, sort: 'longest_waiting' },
      sortOrder: 0,
      createdAt: iso(20),
    },
    {
      id: nextId(),
      workspaceId: SEED_WORKSPACE_ID,
      name: 'Hot leads',
      ownerUserId: CURRENT_USER.id,
      ownerName: CURRENT_USER.name,
      isShared: true,
      filter: { statuses: ['OPEN', 'SNOOZED'], lifecycleStageIds: ['stg-hot-lead'], sort: 'newest' },
      sortOrder: 1,
      createdAt: iso(14),
    },
    {
      id: nextId(),
      workspaceId: SEED_WORKSPACE_ID,
      name: 'VIP watchlist',
      ownerUserId: OTHER_USER.id,
      ownerName: OTHER_USER.name,
      isShared: true,
      filter: { tagIds: [tagId('VIP')], sort: 'unreplied_first' },
      sortOrder: 2,
      createdAt: iso(9),
    },
    {
      id: nextId(),
      workspaceId: SEED_WORKSPACE_ID,
      name: 'Urgent all',
      ownerUserId: CURRENT_USER.id,
      ownerName: CURRENT_USER.name,
      isShared: false,
      filter: { priority: 'URGENT', statuses: ['OPEN'], sort: 'oldest' },
      sortOrder: 3,
      createdAt: iso(3),
    },
  ];
}

let views: InboxView[] = seed();

/** Reset mock state between tests / a fresh browser session. */
export function __mockResetInboxViews(): void {
  views = seed();
}

function validateName(name: string, excludingId?: string): string | null {
  if (!name.trim()) return 'Name is required.';
  if (name.length > 200) return 'Name must be 200 characters or fewer.';
  const dup = views.some(
    (v) => v.id !== excludingId && v.name.trim().toLowerCase() === name.trim().toLowerCase(),
  );
  if (dup) return 'A view with this name already exists.';
  return null;
}

function fieldErrorsError(message: string, fieldErrors: Record<string, string>): ApiError {
  return new ApiError(message, 422, null, { fieldErrors });
}

export const mockInboxViewService: InboxViewService = {
  async list(workspaceId) {
    void workspaceId;
    return delay([...views].sort((a, b) => a.sortOrder - b.sortOrder));
  },

  async create(workspaceId, input: CreateInboxViewInput) {
    const nameError = validateName(input.name);
    if (nameError) throw fieldErrorsError(nameError, { name: nameError });
    if (views.length >= MAX_VIEWS) {
      throw new ApiError(`A workspace may have at most ${MAX_VIEWS} saved views.`, 422);
    }
    const created: InboxView = {
      id: nextId(),
      workspaceId,
      name: input.name.trim(),
      ownerUserId: CURRENT_USER.id,
      ownerName: CURRENT_USER.name,
      isShared: input.isShared,
      filter: input.filter,
      sortOrder: views.length,
      createdAt: new Date().toISOString(),
    };
    views = [...views, created];
    return delay(created);
  },

  async update(workspaceId, id, input: UpdateInboxViewInput) {
    void workspaceId;
    const existing = views.find((v) => v.id === id);
    if (!existing) throw new ApiError('View not found.', 404);
    if (input.name !== undefined) {
      const nameError = validateName(input.name, id);
      if (nameError) throw fieldErrorsError(nameError, { name: nameError });
    }
    const updated: InboxView = {
      ...existing,
      name: input.name !== undefined ? input.name.trim() : existing.name,
      isShared: input.isShared ?? existing.isShared,
      filter: input.filter ?? existing.filter,
      sortOrder: input.sortOrder ?? existing.sortOrder,
    };
    views = views.map((v) => (v.id === id ? updated : v));
    return delay(updated);
  },

  async remove(workspaceId, id) {
    void workspaceId;
    if (!views.some((v) => v.id === id)) throw new ApiError('View not found.', 404);
    views = views.filter((v) => v.id !== id);
    await delay(undefined);
  },
};
