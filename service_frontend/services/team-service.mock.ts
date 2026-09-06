/**
 * Mock team service (plan 28) - retained for component/hook tests only; the
 * real backend (`team-service.real.ts`) is bound in `team-service.ts` since
 * S5. In-memory store, seeded ONCE from the REAL tenant users list
 * (`userService.list`, already wired to the live backend) so Members/Leads
 * are real people, not fabricated names - the current signed-in tenant user
 * (matched by `NEXT_PUBLIC_DEMO_EMAIL`, falling back to `demo@example.com`)
 * lands in TWO of the four seeded teams. One team (`Onboarding`) is
 * pre-flagged as "in use" so the delete-blocked (409 `team_in_use`) error
 * state is exercisable in a test with no backend reference guard.
 */
import { ApiError } from '@/lib/api-client';
import { userService } from '@/services/user-service';
import type { ListQuery, ListResult } from '@/types/resource';
import type { CreateTeamInput, Team, TeamMemberRef, UpdateTeamInput } from '@/types/team';
import type { User } from '@/types/user';
import { delay, runQuery, type QueryAdapter } from './mock-query';
import type { TeamService } from './team-service';

const DEMO_EMAIL = 'demo@example.com';
const EPOCH = Date.parse('2026-06-01T09:00:00Z');
const DAY = 86_400_000;

/** Teams whose delete is blocked by a (mocked) reference guard - tunes the
 * 409 `team_in_use` error state ahead of the real guard landing in S1/§3.1. */
const BLOCKED_TEAM_NAMES = new Set(['Onboarding']);

let rows: Team[] = [];
let seedPromise: Promise<Team[]> | null = null;

function toMemberRef(user: User, role: 'member' | 'lead'): TeamMemberRef {
  return { userId: user.id, name: user.name ?? user.email, email: user.email, role };
}

async function buildSeed(): Promise<Team[]> {
  let users: User[] = [];
  try {
    const res = await userService.list({ page: 0, pageSize: 200, sort: null });
    users = res.data;
  } catch {
    users = []; // degrade to zero-member teams rather than fail the whole surface
  }

  const demo = users.find((u) => u.email.toLowerCase() === DEMO_EMAIL) ?? users[0];
  const others = users.filter((u) => u.id !== demo?.id);
  const pick = (n: number, offset: number): User[] =>
    others.slice(offset % Math.max(others.length, 1), offset % Math.max(others.length, 1) + n);

  const groups: {
    name: string;
    description: string;
    isActive: boolean;
    members: TeamMemberRef[];
  }[] = [
    {
      name: 'Sales',
      description: 'Inbound leads and pricing questions.',
      isActive: true,
      members: [
        ...(demo ? [toMemberRef(demo, 'lead')] : []),
        ...pick(2, 0).map((u) => toMemberRef(u, 'member')),
      ],
    },
    {
      name: 'Support',
      description: 'Post-sale support and account issues.',
      isActive: true,
      members: [
        ...(demo ? [toMemberRef(demo, 'member')] : []),
        ...pick(2, 2).map((u) => toMemberRef(u, 'member')),
      ],
    },
    {
      name: 'Onboarding',
      description: 'New-customer setup and welcome flows.',
      isActive: true,
      members: pick(2, 1).map((u, i) => toMemberRef(u, i === 0 ? 'lead' : 'member')),
    },
    {
      name: 'Billing',
      description: 'Invoices, refunds and payment disputes.',
      isActive: false,
      members: pick(1, 3).map((u) => toMemberRef(u, 'member')),
    },
  ];

  return groups.map((g, i) => {
    const createdAt = new Date(EPOCH - (i + 1) * DAY * 3).toISOString();
    return {
      id: `team-${String(i + 1).padStart(3, '0')}`,
      name: g.name,
      description: g.description,
      isActive: g.isActive,
      sortOrder: i,
      members: g.members,
      memberCount: g.members.length,
      createdAt,
      updatedAt: createdAt,
    } satisfies Team;
  });
}

async function ensureSeeded(): Promise<Team[]> {
  if (rows.length) return rows;
  seedPromise ??= buildSeed();
  rows = await seedPromise;
  return rows;
}

const adapter: QueryAdapter<Team> = {
  searchFields: ['name', 'description'],
  getField: (row, field) => {
    switch (field) {
      case 'created':
        return row.createdAt;
      case 'status':
        return row.isActive ? 'active' : 'inactive';
      default:
        return (row as unknown as Record<string, unknown>)[field];
    }
  },
};

function nameTaken(name: string, excludeId?: string): boolean {
  const norm = name.trim().toLowerCase();
  return rows.some((r) => r.id !== excludeId && r.name.trim().toLowerCase() === norm);
}

async function validateMembers(
  members: { userId: string; role: string }[],
): Promise<TeamMemberRef[]> {
  const { data: users } = await userService.list({ page: 0, pageSize: 200, sort: null });
  const byId = new Map(users.map((u) => [u.id, u]));
  const resolved: TeamMemberRef[] = [];
  for (const m of members) {
    if (m.role !== 'member' && m.role !== 'lead') {
      throw new ApiError('Please fix the highlighted fields.', 422, null, {
        fieldErrors: { members: 'Each member must be "member" or "lead".' },
      });
    }
    const user = byId.get(m.userId);
    if (!user) {
      throw new ApiError('Please fix the highlighted fields.', 422, null, {
        fieldErrors: { members: 'One of the selected members no longer exists.' },
      });
    }
    resolved.push(toMemberRef(user, m.role));
  }
  return resolved;
}

function validateName(name: string, excludeId?: string): void {
  const trimmed = name.trim();
  if (!trimmed) {
    throw new ApiError('Please fix the highlighted fields.', 422, null, {
      fieldErrors: { name: 'Name is required.' },
    });
  }
  if (trimmed.length > 120) {
    throw new ApiError('Please fix the highlighted fields.', 422, null, {
      fieldErrors: { name: 'Name is too long.' },
    });
  }
  if (nameTaken(trimmed, excludeId)) {
    throw new ApiError('Please fix the highlighted fields.', 422, null, {
      fieldErrors: { name: 'A team with this name already exists.' },
    });
  }
}

export const mockTeamService: TeamService = {
  async list(query: ListQuery): Promise<ListResult<Team>> {
    await ensureSeeded();
    return delay(runQuery(rows, query, adapter));
  },

  async get(id: string): Promise<Team> {
    await ensureSeeded();
    const team = rows.find((r) => r.id === id);
    if (!team) throw new ApiError('Team not found.', 404);
    return delay(team);
  },

  async getAt(query: ListQuery, index: number): Promise<{ team: Team | null; total: number }> {
    await ensureSeeded();
    const { data, total } = runQuery(rows, { ...query, page: 0, pageSize: rows.length || 1 }, adapter);
    return delay({ team: data[index] ?? null, total });
  },

  async mine(): Promise<Team[]> {
    await ensureSeeded();
    let users: User[] = [];
    try {
      users = (await userService.list({ page: 0, pageSize: 200, sort: null })).data;
    } catch {
      users = [];
    }
    const demo = users.find((u) => u.email.toLowerCase() === DEMO_EMAIL);
    if (!demo) return delay([]);
    return delay(rows.filter((r) => r.members.some((m) => m.userId === demo.id)));
  },

  async create(input: CreateTeamInput): Promise<Team> {
    await ensureSeeded();
    validateName(input.name);
    const members = await validateMembers(input.members ?? []);
    const now = new Date().toISOString();
    const team: Team = {
      id: `team-${Math.random().toString(36).slice(2, 10)}`,
      name: input.name.trim(),
      description: input.description?.trim() || null,
      isActive: input.isActive ?? true,
      sortOrder: input.sortOrder ?? rows.length,
      members,
      memberCount: members.length,
      createdAt: now,
      updatedAt: now,
    };
    rows = [...rows, team];
    return delay(team);
  },

  async update(id: string, input: UpdateTeamInput): Promise<Team> {
    await ensureSeeded();
    const existing = rows.find((r) => r.id === id);
    if (!existing) throw new ApiError('Team not found.', 404);
    if (input.name !== undefined) validateName(input.name, id);
    const members =
      input.members !== undefined ? await validateMembers(input.members) : existing.members;
    const updated: Team = {
      ...existing,
      name: input.name !== undefined ? input.name.trim() : existing.name,
      description:
        input.description !== undefined ? (input.description?.trim() || null) : existing.description,
      isActive: input.isActive ?? existing.isActive,
      sortOrder: input.sortOrder ?? existing.sortOrder,
      members,
      memberCount: members.length,
      updatedAt: new Date().toISOString(),
    };
    rows = rows.map((r) => (r.id === id ? updated : r));
    return delay(updated);
  },

  async remove(id: string): Promise<void> {
    await ensureSeeded();
    const team = rows.find((r) => r.id === id);
    if (!team) throw new ApiError('Team not found.', 404);
    if (BLOCKED_TEAM_NAMES.has(team.name)) {
      throw new ApiError('This team is in use.', 409, null, {
        error: 'team_in_use',
        counts: { conversations: 3 },
      });
    }
    rows = rows.filter((r) => r.id !== id);
    return delay(undefined);
  },
};
