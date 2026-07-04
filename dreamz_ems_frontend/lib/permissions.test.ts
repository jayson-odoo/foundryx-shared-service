import { describe, expect, it } from 'vitest';
import {
  actionOf,
  applyImpliedRead,
  keysForResource,
  mergeResourceGrants,
  normalizeResourceGrants,
  readKeyFor,
  resourceOf,
  splitKey,
} from './permissions';

describe('key parsing', () => {
  it('splits resource.action', () => {
    expect(splitKey('users.create')).toEqual({ resource: 'users', action: 'create' });
    expect(resourceOf('orders.approve')).toBe('orders');
    expect(actionOf('orders.approve')).toBe('approve');
  });

  it('readKeyFor builds the read key', () => {
    expect(readKeyFor('events')).toBe('events.read');
  });

  it('keysForResource filters by resource', () => {
    const all = ['users.read', 'users.create', 'events.read'];
    expect(keysForResource(all, 'users')).toEqual(['users.read', 'users.create']);
    expect(keysForResource(all, 'events')).toEqual(['events.read']);
  });
});

describe('implied-read (blanket — any action implies read)', () => {
  it('adds read when a standard write is present', () => {
    expect(applyImpliedRead(['users.create'])).toEqual(
      expect.arrayContaining(['users.create', 'users.read']),
    );
  });

  it('adds read for a CUSTOM action (e.g. approve)', () => {
    const out = applyImpliedRead(['orders.approve']);
    expect(out).toContain('orders.approve');
    expect(out).toContain('orders.read');
  });

  it('read alone implies nothing extra', () => {
    expect(applyImpliedRead(['users.read'])).toEqual(['users.read']);
  });

  it('does not cross resources', () => {
    const out = applyImpliedRead(['users.create', 'events.read']);
    expect(out).toContain('users.read');
    expect(out.filter((k) => k === 'events.read')).toHaveLength(1);
    expect(out).not.toContain('events.create');
  });

  it('is idempotent + de-duplicated', () => {
    const once = applyImpliedRead(['users.create', 'users.read']);
    expect(applyImpliedRead(once).sort()).toEqual(once.sort());
    expect(once.filter((k) => k === 'users.read')).toHaveLength(1);
  });
});

describe('normalizeResourceGrants (per-resource lock)', () => {
  it('forces read in when a write is selected', () => {
    expect(normalizeResourceGrants('users', ['users.delete'])).toEqual(
      expect.arrayContaining(['users.delete', 'users.read']),
    );
  });

  it('keeps empty selection empty (no access)', () => {
    expect(normalizeResourceGrants('users', [])).toEqual([]);
  });

  it('ignores keys from other resources', () => {
    expect(normalizeResourceGrants('users', ['users.update', 'events.read'])).toEqual(
      expect.arrayContaining(['users.update', 'users.read']),
    );
    expect(normalizeResourceGrants('users', ['users.update', 'events.read'])).not.toContain(
      'events.read',
    );
  });
});

describe('mergeResourceGrants (write back into flat grant set)', () => {
  it('replaces only the target resource slice, normalizing read', () => {
    const out = mergeResourceGrants(['events.read'], 'orders', ['orders.update']);
    expect(out).toContain('events.read');
    expect(out).toContain('orders.update');
    expect(out).toContain('orders.read');
  });

  it('clearing a resource removes its read too', () => {
    const out = mergeResourceGrants(['events.read', 'users.create', 'users.read'], 'users', []);
    expect(out).toEqual(['events.read']);
  });

  it('leaves other resources untouched', () => {
    const out = mergeResourceGrants(
      ['events.read', 'events.create', 'users.read'],
      'users',
      ['users.read', 'users.update'],
    );
    expect(out).toContain('events.read');
    expect(out).toContain('events.create');
    expect(out).toContain('users.update');
  });
});
