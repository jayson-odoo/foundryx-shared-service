import { describe, expect, it } from 'vitest';
import { workspaceFormSchema } from './workspace-schema';

describe('workspaceFormSchema', () => {
  it('accepts a valid workspace', () => {
    const r = workspaceFormSchema.safeParse({ name: 'Sales & Support', status: 'ACTIVE' });
    expect(r.success).toBe(true);
  });

  it('rejects an empty name', () => {
    const r = workspaceFormSchema.safeParse({ name: '   ', status: 'ACTIVE' });
    expect(r.success).toBe(false);
  });

  it('rejects an unknown status', () => {
    const r = workspaceFormSchema.safeParse({ name: 'X', status: 'ARCHIVED' });
    expect(r.success).toBe(false);
  });
});
