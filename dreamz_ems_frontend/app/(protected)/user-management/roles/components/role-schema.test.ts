import { describe, expect, it } from 'vitest';
import { roleFormSchema } from './role-schema';

describe('roleFormSchema', () => {
  const valid = {
    name: 'Event Manager',
    description: 'Runs events',
    permissionKeys: ['events.read'],
    isSystem: false,
  };

  it('accepts a valid role', () => {
    expect(roleFormSchema.safeParse(valid).success).toBe(true);
  });

  it('requires a name', () => {
    const r = roleFormSchema.safeParse({ ...valid, name: '   ' });
    expect(r.success).toBe(false);
  });

  it('rejects an over-long name', () => {
    const r = roleFormSchema.safeParse({ ...valid, name: 'x'.repeat(81) });
    expect(r.success).toBe(false);
  });

  it('rejects an over-long description', () => {
    const r = roleFormSchema.safeParse({ ...valid, description: 'x'.repeat(241) });
    expect(r.success).toBe(false);
  });

  it('allows an empty description + empty permission set', () => {
    expect(
      roleFormSchema.safeParse({ name: 'Viewer', description: '', permissionKeys: [], isSystem: false })
        .success,
    ).toBe(true);
  });
});
