import { describe, expect, it } from 'vitest';
import type { MigrationJobStatus } from '@/types/respondio-migration';
import { MIGRATION_STATUS_REGISTRY, MIGRATION_STATUS_SEGMENTS } from './migration-status';

const ALL_STATUSES: MigrationJobStatus[] = ['pending', 'running', 'needs_review', 'done', 'failed', 'aborted'];

describe('MIGRATION_STATUS_REGISTRY', () => {
  it('declares a label + tone for every MigrationJobStatus', () => {
    for (const status of ALL_STATUSES) {
      expect(MIGRATION_STATUS_REGISTRY[status]).toBeDefined();
      expect(MIGRATION_STATUS_REGISTRY[status].label.length).toBeGreaterThan(0);
    }
  });
});

describe('MIGRATION_STATUS_SEGMENTS', () => {
  it('covers "all" plus every status exactly once', () => {
    const ids = MIGRATION_STATUS_SEGMENTS.map((s) => s.id);
    expect(ids[0]).toBe('all');
    for (const status of ALL_STATUSES) {
      expect(ids.filter((id) => id === status)).toHaveLength(1);
    }
  });
});
