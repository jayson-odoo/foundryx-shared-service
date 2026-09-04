/**
 * `presentContinuous` (countdown copy) + fix round 1 item 13's
 * `pastTense`/`entityNoun`/`deferredDoneMessage` (commit-toast copy -
 * "User trashed." / "3 users trashed." instead of a bare "Done.").
 */
import { describe, expect, it } from 'vitest';
import {
  deferredDoneMessage,
  entityNoun,
  pastTense,
  presentContinuous,
} from './deferred-verb';

describe('presentContinuous', () => {
  it('conjugates the leading verb only', () => {
    expect(presentContinuous('Delete')).toBe('Deleting');
    expect(presentContinuous('Delete permanently')).toBe('Deleting permanently');
    expect(presentContinuous('Trash')).toBe('Trashing');
  });
});

describe('pastTense', () => {
  it('conjugates regular verbs', () => {
    expect(pastTense('Delete')).toBe('Deleted');
    expect(pastTense('Trash')).toBe('Trashed');
    expect(pastTense('Archive')).toBe('Archived');
    expect(pastTense('Disconnect')).toBe('Disconnected');
    expect(pastTense('Revoke')).toBe('Revoked');
    expect(pastTense('Suspend')).toBe('Suspended');
    expect(pastTense('Reactivate')).toBe('Reactivated');
  });

  it('keeps the trailing words and handles multi-word labels', () => {
    expect(pastTense('Delete permanently')).toBe('Deleted permanently');
    expect(pastTense('Delete role')).toBe('Deleted role');
  });

  it('leaves irregular verbs already in their past form', () => {
    expect(pastTense('Reset to default')).toBe('Reset to default');
    expect(pastTense('Set as active')).toBe('Set as active');
  });
});

describe('entityNoun', () => {
  it('singularizes for count 1, pluralizes above', () => {
    expect(entityNoun('user', 1)).toBe('user');
    expect(entityNoun('user', 3)).toBe('users');
    expect(entityNoun('ai_agent', 1)).toBe('AI agent');
    expect(entityNoun('ai_agent', 2)).toBe('AI agents');
  });

  it('falls back to a naive plural for an unmapped type', () => {
    expect(entityNoun('widget', 2)).toBe('widgets');
  });
});

describe('deferredDoneMessage', () => {
  it('single record reads "Noun verbed." - only the LEADING verb is used, never a duplicated noun', () => {
    expect(deferredDoneMessage('Trash', 'user', 1)).toBe('User trashed.');
    expect(deferredDoneMessage('Delete role', 'role', 1)).toBe('Role deleted.');
    expect(deferredDoneMessage('Delete permanently', 'workflow', 1)).toBe('Workflow deleted.');
  });

  it('bulk reads "N nouns verbed."', () => {
    expect(deferredDoneMessage('Trash', 'user', 3)).toBe('3 users trashed.');
  });
});
