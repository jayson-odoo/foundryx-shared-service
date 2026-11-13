/**
 * Mock contact-segment service (S0, plan 26). Single-workspace in-memory
 * store seeded with 3 segments built ONLY on system columns (priority,
 * assignee, lastMessageAt) so they stay valid regardless of which real tags /
 * custom fields the workspace happens to have. Mirrors the backend rules
 * (AC-CTM-20): unique name (case-insensitive), 100-segment cap.
 */
import { ApiError } from '@/lib/api-client';
import type { ContactSegment, CreateContactSegmentInput, UpdateContactSegmentInput } from '@/types/omnichannel';
import type { ContactSegmentService } from './contact-segment-service';
import { delay } from './mock-query';

const MAX_SEGMENTS = 100;

function fieldErrorsError(message: string, fieldErrors: Record<string, string>): ApiError {
  return new ApiError(message, 422, null, { fieldErrors });
}

let idSeq = 1;
const nextId = () => `seg-${idSeq++}`;
const iso = (daysAgo: number) => new Date(Date.now() - daysAgo * 86_400_000).toISOString();

function seed(): ContactSegment[] {
  idSeq = 1;
  return [
    {
      id: nextId(),
      workspaceId: 'wsp-001',
      name: 'Urgent & high priority',
      description: 'Contacts flagged HIGH or URGENT.',
      filter: {
        kind: 'group',
        combinator: 'and',
        rules: [{ kind: 'condition', field: 'priority', operator: 'in', value: ['HIGH', 'URGENT'] }],
      },
      createdAt: iso(20),
      updatedAt: iso(20),
    },
    {
      id: nextId(),
      workspaceId: 'wsp-001',
      name: 'Unassigned',
      description: 'No assignee yet.',
      filter: {
        kind: 'group',
        combinator: 'and',
        rules: [{ kind: 'condition', field: 'assignee', operator: 'eq', value: 'unassigned' }],
      },
      createdAt: iso(12),
      updatedAt: iso(12),
    },
    {
      id: nextId(),
      workspaceId: 'wsp-001',
      name: 'No recent activity',
      description: 'Last message over 30 days ago.',
      filter: {
        kind: 'group',
        combinator: 'and',
        rules: [
          {
            kind: 'condition',
            field: 'lastMessageAt',
            operator: 'before',
            value: iso(30),
          },
        ],
      },
      createdAt: iso(5),
      updatedAt: iso(5),
    },
  ];
}

let segments: ContactSegment[] = seed();

/** Reset mock state between tests / a fresh browser session. */
export function __mockResetContactSegments(): void {
  segments = seed();
}

function validateName(name: string, excludingId?: string): string | null {
  if (!name.trim()) return 'Name is required.';
  const dup = segments.some(
    (s) => s.id !== excludingId && s.name.toLowerCase() === name.trim().toLowerCase(),
  );
  return dup ? 'A segment with this name already exists.' : null;
}

export const mockContactSegmentService: ContactSegmentService = {
  async list(_workspaceId) {
    void _workspaceId;
    const rows = [...segments].sort((a, b) => a.name.localeCompare(b.name));
    return delay(rows, 200);
  },

  async create(workspaceId, input: CreateContactSegmentInput) {
    if (segments.length >= MAX_SEGMENTS) {
      throw fieldErrorsError('This workspace has reached the 100-segment limit.', {
        name: 'This workspace has reached the 100-segment limit.',
      });
    }
    const nameError = validateName(input.name);
    if (nameError) throw fieldErrorsError(nameError, { name: nameError });
    const created: ContactSegment = {
      id: nextId(),
      workspaceId,
      name: input.name.trim(),
      description: input.description?.trim() || null,
      filter: input.filter,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    segments = [...segments, created];
    return delay(created, 300);
  },

  async update(_workspaceId, segmentId, input: UpdateContactSegmentInput) {
    void _workspaceId;
    const existing = segments.find((s) => s.id === segmentId);
    if (!existing) throw new ApiError('Segment not found.', 404, null, null);
    if (input.name !== undefined) {
      const nameError = validateName(input.name, segmentId);
      if (nameError) throw fieldErrorsError(nameError, { name: nameError });
    }
    const updated: ContactSegment = {
      ...existing,
      name: input.name !== undefined ? input.name.trim() : existing.name,
      description: input.description !== undefined ? input.description?.trim() || null : existing.description,
      filter: input.filter ?? existing.filter,
      updatedAt: new Date().toISOString(),
    };
    segments = segments.map((s) => (s.id === segmentId ? updated : s));
    return delay(updated, 300);
  },

  async remove(_workspaceId, segmentId) {
    void _workspaceId;
    segments = segments.filter((s) => s.id !== segmentId);
    return delay(undefined, 200);
  },
};
