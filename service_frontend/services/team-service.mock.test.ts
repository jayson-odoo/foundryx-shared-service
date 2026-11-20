/**
 * Mock team service (plan 28, roadmap A8, S0) - CRUD validation + the
 * "in use" delete guard the real reference-guard will enforce in S1.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const USERS = [
  { id: 'u1', tenantId: 't1', name: 'Ada Lovelace', email: 'ada@example.com', status: 'ACTIVE', avatar: null, roles: [], createdAt: '', lastSignInAt: null, emailVerifiedAt: null, isTrashed: false },
  { id: 'u2', tenantId: 't1', name: 'Demo User', email: 'demo@example.com', status: 'ACTIVE', avatar: null, roles: [], createdAt: '', lastSignInAt: null, emailVerifiedAt: null, isTrashed: false },
];

vi.mock('@/services/user-service', () => ({
  userService: { list: vi.fn().mockResolvedValue({ data: USERS, total: USERS.length, page: 0 }) },
}));

describe('mockTeamService (plan 28)', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('seeds 4 teams with the demo user in exactly 2', async () => {
    const { mockTeamService } = await import('./team-service.mock');
    const { data } = await mockTeamService.list({ page: 0, pageSize: 50, sort: null });
    expect(data).toHaveLength(4);
    const withDemo = data.filter((t) => t.members.some((m) => m.email === 'demo@example.com'));
    expect(withDemo).toHaveLength(2);
  });

  it('mine() returns only the teams the demo user belongs to (trimmed shape, no email)', async () => {
    const { mockTeamService } = await import('./team-service.mock');
    const mine = await mockTeamService.mine();
    expect(mine.length).toBe(2);
    expect(mine.every((t) => t.members.some((m) => m.userId === 'u2'))).toBe(true);
    for (const t of mine) {
      expect(t).not.toHaveProperty('description');
      for (const m of t.members) {
        expect(m).not.toHaveProperty('email');
      }
    }
  });

  it('rejects a blank name with a 422 fieldErrors.name', async () => {
    const { mockTeamService } = await import('./team-service.mock');
    await expect(
      mockTeamService.create({ name: '   ', members: [] }),
    ).rejects.toMatchObject({ status: 422, detail: { fieldErrors: { name: expect.any(String) } } });
  });

  it('rejects a duplicate name case-insensitively (AC-TEM-02)', async () => {
    const { mockTeamService } = await import('./team-service.mock');
    await expect(
      mockTeamService.create({ name: 'sales', members: [] }),
    ).rejects.toMatchObject({ status: 422 });
  });

  it('rejects a member id that does not exist - nothing is written (AC-TEM-03)', async () => {
    const { mockTeamService } = await import('./team-service.mock');
    const before = (await mockTeamService.list({ page: 0, pageSize: 50, sort: null })).total;
    await expect(
      mockTeamService.create({ name: 'Ghosts', members: [{ userId: 'no-such-user', role: 'member' }] }),
    ).rejects.toMatchObject({ status: 422, detail: { fieldErrors: { members: expect.any(String) } } });
    const after = (await mockTeamService.list({ page: 0, pageSize: 50, sort: null })).total;
    expect(after).toBe(before);
  });

  it('creates a team with member + lead roles', async () => {
    const { mockTeamService } = await import('./team-service.mock');
    const team = await mockTeamService.create({
      name: 'Ops Desk',
      members: [
        { userId: 'u1', role: 'lead' },
        { userId: 'u2', role: 'member' },
      ],
    });
    expect(team.members).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ userId: 'u1', role: 'lead' }),
        expect.objectContaining({ userId: 'u2', role: 'member' }),
      ]),
    );
  });

  it('delete returns 409 team_in_use with counts for a blocked team; nothing is removed', async () => {
    const { mockTeamService } = await import('./team-service.mock');
    const { data } = await mockTeamService.list({ page: 0, pageSize: 50, sort: null });
    const blocked = data.find((t) => t.name === 'Onboarding')!;

    let caught: { status?: number; detail?: unknown } | undefined;
    try {
      await mockTeamService.remove(blocked.id);
    } catch (e) {
      caught = e as { status?: number; detail?: unknown };
    }
    expect(caught?.status).toBe(409);
    expect(caught?.detail).toMatchObject({ error: 'team_in_use' });

    const stillThere = (await mockTeamService.list({ page: 0, pageSize: 50, sort: null })).data.some(
      (t) => t.id === blocked.id,
    );
    expect(stillThere).toBe(true);
  });

  it('delete succeeds (204) for a team with no reference-guard usage', async () => {
    const { mockTeamService } = await import('./team-service.mock');
    const { data } = await mockTeamService.list({ page: 0, pageSize: 50, sort: null });
    const deletable = data.find((t) => t.name === 'Sales')!;
    await expect(mockTeamService.remove(deletable.id)).resolves.toBeUndefined();
  });
});
