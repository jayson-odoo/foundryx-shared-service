/**
 * Mock contact-tag service (S0, plan 25). In-memory store, seeded with a few
 * tags (emoji + colour) so the Tags tab + the panel's tag picker are tunable
 * with no backend. Mirrors the backend rules (AC-CDM-09/11): unique name
 * (case-insensitive), 500-tag cap.
 *
 * Single-workspace mock (same reasoning as contact-field-service.mock):
 * `workspaceId` is accepted + stamped on created rows but NOT used to filter -
 * `workspace-service` is REAL and returns a real UUID, so every call sees the
 * one seeded set regardless of which real workspace is open.
 */
import { ApiError } from '@/lib/api-client';
import type { ContactTag, CreateContactTagInput, UpdateContactTagInput } from '@/types/omnichannel';
import type { ContactTagService } from './contact-tag-service';
import { delay } from './mock-query';

const MAX_TAGS = 500;
const SEED_WORKSPACE_ID = 'wsp-001'; // cosmetic default; never filtered on

let idSeq = 1;
const nextId = () => `tag-${idSeq++}`;
const iso = (daysAgo: number) => new Date(Date.now() - daysAgo * 86_400_000).toISOString();

function fieldErrorsError(message: string, fieldErrors: Record<string, string>): ApiError {
  return new ApiError(message, 422, null, { fieldErrors });
}

function seed(): ContactTag[] {
  idSeq = 1;
  return [
    {
      id: nextId(),
      workspaceId: SEED_WORKSPACE_ID,
      name: 'VIP',
      emoji: '⭐',
      color: '#F59E0B',
      description: 'High-value client - handle with priority.',
      contactsCount: 2,
      createdAt: iso(25),
    },
    {
      id: nextId(),
      workspaceId: SEED_WORKSPACE_ID,
      name: 'Follow up',
      emoji: '📌',
      color: '#3B82F6',
      description: null,
      contactsCount: 1,
      createdAt: iso(15),
    },
    {
      id: nextId(),
      workspaceId: SEED_WORKSPACE_ID,
      name: 'Spam',
      emoji: '🚫',
      color: '#EF4444',
      description: null,
      contactsCount: 0,
      createdAt: iso(5),
    },
  ];
}

let tags: ContactTag[] = seed();

/** Reset mock state between tests / a fresh browser session. */
export function __mockResetContactTags(): void {
  tags = seed();
}

/** Cross-mock read used by conversation-service.mock.ts to validate + resolve
 *  `tagIds` on a contact PATCH (S0 only - the real backend joins the same
 *  workspace-scoped table server-side). `workspaceId` accepted, not filtered. */
export function __mockAllContactTags(_workspaceId: string): ContactTag[] {
  void _workspaceId;
  return [...tags];
}

function validateName(name: string, excludingId?: string): string | null {
  if (!name.trim()) return 'Name is required.';
  const dup = tags.some((t) => t.id !== excludingId && t.name.toLowerCase() === name.trim().toLowerCase());
  return dup ? 'A tag with this name already exists.' : null;
}

export const mockContactTagService: ContactTagService = {
  async list(_workspaceId) {
    void _workspaceId;
    const rows = [...tags].sort((a, b) => a.name.localeCompare(b.name));
    return delay(rows, 200);
  },

  async create(workspaceId, input: CreateContactTagInput) {
    if (tags.length >= MAX_TAGS) {
      throw fieldErrorsError('This workspace has reached the 500-tag limit.', {
        name: 'This workspace has reached the 500-tag limit.',
      });
    }
    const nameError = validateName(input.name);
    if (nameError) throw fieldErrorsError(nameError, { name: nameError });
    const created: ContactTag = {
      id: nextId(),
      workspaceId,
      name: input.name.trim(),
      emoji: input.emoji?.trim() || null,
      color: input.color?.trim() || null,
      description: input.description?.trim() || null,
      contactsCount: 0,
      createdAt: new Date().toISOString(),
    };
    tags = [...tags, created];
    return delay(created, 250);
  },

  async update(_workspaceId, tagId, input: UpdateContactTagInput) {
    void _workspaceId;
    const existing = tags.find((t) => t.id === tagId);
    if (!existing) throw new Error('Tag not found.');
    if (input.name !== undefined) {
      const nameError = validateName(input.name, tagId);
      if (nameError) throw fieldErrorsError(nameError, { name: nameError });
    }
    const updated: ContactTag = {
      ...existing,
      name: input.name !== undefined ? input.name.trim() : existing.name,
      emoji: input.emoji !== undefined ? input.emoji?.trim() || null : existing.emoji,
      color: input.color !== undefined ? input.color?.trim() || null : existing.color,
      description:
        input.description !== undefined ? input.description?.trim() || null : existing.description,
    };
    tags = tags.map((t) => (t.id === tagId ? updated : t));
    return delay(updated, 250);
  },

  async remove(_workspaceId, tagId) {
    void _workspaceId;
    tags = tags.filter((t) => t.id !== tagId);
    return delay(undefined, 200);
  },
};
