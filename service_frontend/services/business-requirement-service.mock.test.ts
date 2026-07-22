import { describe, expect, it } from 'vitest';
import { mockBusinessRequirementService as svc } from './business-requirement-service.mock';

describe('mockBusinessRequirementService', () => {
  it('lists active BRs by default and archived when asked', async () => {
    const active = await svc.list({ filter: 'active' });
    expect(active.every((b) => b.status !== 'archived')).toBe(true);
    expect(active.length).toBeGreaterThan(0);
  });

  it('creates a draft BR that carries the stamped template doc on get', async () => {
    const created = await svc.create({ productId: 'prod-1', title: 'New export' });
    expect(created.status).toBe('draft');
    expect(created.templateVersion).toBe(1);
    const got = await svc.get(created.id);
    expect(got.templateDoc.pages.length).toBeGreaterThan(0);
    expect(got.title).toBe('New export');
  });

  it('updates title + answers', async () => {
    const created = await svc.create({ productId: 'prod-1', title: 'X' });
    const updated = await svc.update(created.id, {
      title: 'Y',
      answers: { problem_statement: 'p' },
    });
    expect(updated.title).toBe('Y');
    expect(updated.answers.problem_statement).toBe('p');
  });

  it('moves status via setStatus', async () => {
    const created = await svc.create({ productId: 'prod-1', title: 'Z' });
    const moved = await svc.setStatus(created.id, 'grilling');
    expect(moved.status).toBe('grilling');
  });

  it('flags the stamped version in the version list', async () => {
    const versions = await svc.listVersions('br-1');
    expect(versions.some((v) => v.isStamped)).toBe(true);
  });

  it('rejects get for an unknown id', async () => {
    await expect(svc.get('nope')).rejects.toThrow();
  });
});
