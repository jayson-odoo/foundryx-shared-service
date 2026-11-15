import { describe, expect, it } from 'vitest';
import type { PermissionResource } from '@/types/permission';
import { groupPermissionsByModule } from './group-permissions';

const res = (resource: string, module: string, moduleLabel?: string): PermissionResource => ({
  resource,
  resourceLabel: resource,
  module,
  moduleLabel,
  actions: [],
});

// Crew pass 34455d5: the Roles editor printed the raw module key ("IDEATION")
// as the section header. The header is the module's human label.
describe('groupPermissionsByModule', () => {
  it('groups by module and heads each group with its label, never the key', () => {
    const groups = groupPermissionsByModule([
      res('users', 'core', 'Core'),
      res('ideation.ideas', 'ideation', 'Feedback'),
      res('ideation.triage', 'ideation', 'Feedback'),
    ]);
    expect(groups.map((g) => g.label)).toEqual(['Core', 'Feedback']);
    expect(groups[1].resources).toHaveLength(2);
  });
  it('falls back to a readable word when an older backend sends no label', () => {
    expect(groupPermissionsByModule([res('x.y', 'autocount')])[0].label).toBe('Autocount');
  });
});
