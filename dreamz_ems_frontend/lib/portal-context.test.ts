import { describe, expect, it } from 'vitest';
import type { PortalSurface } from '@/services/portal-surface-service';
import {
  activeContextScopeId,
  contextKey,
  contextLabel,
  contextsForSurface,
  filterSurfaces,
  unionContexts,
} from './portal-context';

const surfaces: PortalSurface[] = [
  {
    key: 'a',
    label: 'A',
    gatingPermission: 'a.read',
    module: 'ems',
    sortOrder: 1,
    description: null,
    contexts: [
      { scopeType: 'project', scopeId: 'p1' },
      { scopeType: 'project', scopeId: 'p2' },
    ],
  },
  {
    key: 'b',
    label: 'B',
    gatingPermission: 'b.read',
    module: 'ems',
    sortOrder: 2,
    description: null,
    contexts: [{ scopeType: 'project', scopeId: 'p1' }],
  },
];

describe('portal-context helpers', () => {
  it('labels tenant scope "Tenant-wide" and project scope "Event {id8}"', () => {
    expect(contextLabel({ scopeType: 'tenant', scopeId: null })).toBe('Tenant-wide');
    expect(contextLabel({ scopeType: 'project', scopeId: null })).toBe('Tenant-wide');
    expect(contextLabel({ scopeType: 'project', scopeId: 'abcdefghij' })).toBe(
      'Event abcdefgh',
    );
  });

  it('prefers the server-resolved event name (AC-06-25)', () => {
    expect(
      contextLabel({ scopeType: 'project', scopeId: 'p1', label: 'Annual Summit' }),
    ).toBe('Annual Summit');
  });

  it('activeContextScopeId returns the project scope id, null for tenant/none', () => {
    expect(activeContextScopeId('project:p1')).toBe('p1');
    expect(activeContextScopeId('tenant:')).toBeNull();
    expect(activeContextScopeId(null)).toBeNull();
    expect(activeContextScopeId('project:')).toBeNull();
  });

  it('contextKey is stable across surfaces', () => {
    expect(contextKey({ scopeType: 'project', scopeId: 'p1' })).toBe('project:p1');
    expect(contextKey({ scopeType: 'tenant', scopeId: null })).toBe('tenant:');
  });

  it('unionContexts de-duplicates and sorts', () => {
    const union = unionContexts(surfaces);
    expect(union.map((u) => u.key)).toEqual(['project:p1', 'project:p2']);
  });

  it('filterSurfaces returns all when unfiltered, the matching set otherwise', () => {
    expect(filterSurfaces(surfaces, null)).toHaveLength(2);
    expect(filterSurfaces(surfaces, 'project:p2').map((s) => s.key)).toEqual(['a']);
  });

  it('contextsForSurface narrows to the active filter', () => {
    expect(contextsForSurface(surfaces[0], null)).toHaveLength(2);
    expect(contextsForSurface(surfaces[0], 'project:p2')).toEqual([
      { scopeType: 'project', scopeId: 'p2' },
    ]);
  });
});
