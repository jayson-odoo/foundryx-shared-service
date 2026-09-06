import { describe, expect, it } from 'vitest';
import {
  computeMappingHash,
  EMPTY_MIGRATION_FORM_VALUES,
  migrationFormSchema,
  toCreateMigrationJobInput,
  type MigrationFormValues,
} from './migration-schema';

describe('migrationFormSchema', () => {
  it('rejects a form with no connection, workspace, or channel map', () => {
    const result = migrationFormSchema.safeParse(EMPTY_MIGRATION_FORM_VALUES);
    expect(result.success).toBe(false);
  });

  it('accepts a filled-in form (channel map completeness satisfied)', () => {
    const values: MigrationFormValues = {
      ...EMPTY_MIGRATION_FORM_VALUES,
      connectionId: 'conn-1',
      workspaceId: 'wsp-1',
      channelMap: [{ sourceChannelId: 'rio-chn-1', targetChannelId: 'chn-1' }],
    };
    expect(migrationFormSchema.safeParse(values).success).toBe(true);
  });
});

describe('computeMappingHash', () => {
  const base = {
    connectionId: 'conn-1',
    workspaceId: 'wsp-1',
    channelMap: [
      { sourceChannelId: 'a', targetChannelId: 'x' },
      { sourceChannelId: 'b', targetChannelId: null },
    ],
    userMap: [{ sourceUserId: 'u1', targetUserId: 'usr-1' }],
    teamMap: [{ sourceTeamId: 't1', targetTeamId: null }],
    lifecycleMap: [{ sourceLabel: 'lead', targetStatusId: 'stg-1' }],
    contactsOnly: false,
    messagesSince: null,
  };

  it('is stable for the identical input (mapping hash stability, AC-MIG-58)', () => {
    expect(computeMappingHash(base)).toBe(computeMappingHash({ ...base }));
  });

  it('is stable regardless of array ORDER within each map', () => {
    const reordered = {
      ...base,
      channelMap: [...base.channelMap].reverse(),
    };
    expect(computeMappingHash(base)).toBe(computeMappingHash(reordered));
  });

  it('changes when a single mapped target changes', () => {
    const changed = {
      ...base,
      channelMap: [{ sourceChannelId: 'a', targetChannelId: 'DIFFERENT' }, base.channelMap[1]],
    };
    expect(computeMappingHash(base)).not.toBe(computeMappingHash(changed));
  });

  it('changes when the connection or workspace differs', () => {
    expect(computeMappingHash(base)).not.toBe(computeMappingHash({ ...base, workspaceId: 'wsp-2' }));
    expect(computeMappingHash(base)).not.toBe(computeMappingHash({ ...base, connectionId: 'conn-2' }));
  });

  it('is independent of `mode` (a dry run and its matching real run share one hash)', () => {
    const dryRunInput = toCreateMigrationJobInput({ ...EMPTY_MIGRATION_FORM_VALUES, ...base, source: 'api' }, 'dry_run');
    const runInput = toCreateMigrationJobInput({ ...EMPTY_MIGRATION_FORM_VALUES, ...base, source: 'api' }, 'run');
    expect(computeMappingHash(dryRunInput)).toBe(computeMappingHash(runInput));
  });
});
