/**
 * The one whitelisted contact-filter field list (review round 1, B3) - the
 * broadcasts audience Filter builder used to hand-roll its OWN copy
 * (`status`/hardcoded-`assignee`/`priority`) which the backend's
 * `contact_filters.py` whitelist rejects with a 422 for `status` - a
 * foolproof-UI violation (a picker offering a choice guaranteed to fail).
 * `useContactFilterFields` is now the ONE source both the Contacts list and
 * the broadcasts audience builder read from.
 */
import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ContactField, ContactTag, WorkspaceMember } from '@/types/omnichannel';
import type { LifecycleStageOption } from '@/hooks/use-contact-lifecycle-stages';
import { useContactFilterFields } from './use-contact-filter-fields';

const TAGS: ContactTag[] = [{ id: 'tag-1', name: 'VIP', emoji: '⭐' } as ContactTag];
const STAGES: LifecycleStageOption[] = [
  { id: 'st-1', key: 'lead', label: 'Lead', color: '#000', isInitial: true, isTerminal: false, isArchived: false },
];
const MEMBERS: WorkspaceMember[] = [{ userId: 'u-1', name: 'Alex', email: 'alex@example.com' } as WorkspaceMember];
const FIELDS: ContactField[] = [
  { key: 'notes', label: 'Notes', type: 'text', visibility: 'always' } as ContactField,
];

describe('useContactFilterFields', () => {
  it('never offers a "status" field (the backend has no such contact filter column)', () => {
    const { result } = renderHook(() =>
      useContactFilterFields({ tags: TAGS, fields: FIELDS, stages: STAGES, members: MEMBERS, channelTypeOptions: [] }),
    );
    expect(result.current.some((f) => f.field === 'status')).toBe(false);
  });

  it('offers only backend-whitelisted system columns plus registered custom fields', () => {
    const { result } = renderHook(() =>
      useContactFilterFields({ tags: TAGS, fields: FIELDS, stages: STAGES, members: MEMBERS, channelTypeOptions: [] }),
    );
    const ids = result.current.map((f) => f.field);
    expect(ids).toEqual(
      expect.arrayContaining([
        'name', 'phone', 'email', 'language', 'countryCode', 'priority', 'assignee',
        'channelType', 'lifecycle', 'tags', 'lastMessageAt', 'createdAt', 'customFields.notes',
      ]),
    );
  });

  it('the assignee field lists real workspace members, not a hardcoded single option', () => {
    const { result } = renderHook(() =>
      useContactFilterFields({ tags: TAGS, fields: FIELDS, stages: STAGES, members: MEMBERS, channelTypeOptions: [] }),
    );
    const assignee = result.current.find((f) => f.field === 'assignee')!;
    expect(assignee.options).toEqual([
      { label: 'Unassigned', value: 'unassigned' },
      { label: 'Alex', value: 'u-1' },
    ]);
  });

  it('a custom field only appears when its visibility is "always"', () => {
    const hidden: ContactField[] = [
      ...FIELDS,
      { key: 'secret', label: 'Secret', type: 'text', visibility: 'hidden' } as ContactField,
    ];
    const { result } = renderHook(() =>
      useContactFilterFields({ tags: TAGS, fields: hidden, stages: STAGES, members: MEMBERS, channelTypeOptions: [] }),
    );
    expect(result.current.some((f) => f.field === 'customFields.secret')).toBe(false);
  });
});
