/**
 * Contacts list config (D-A2-2, AC-CTM-46) - the filterFields whitelist
 * (system columns + `customFields.<key>` for `visibility:'always'` fields
 * only), the exporter/importer/create wiring, and permission gating
 * (`contacts.manage` create, `contacts.import` importer - AC-CTM-46
 * permission-gating target).
 */
import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ContactField, ContactSegment, ContactTag, WorkspaceMember } from '@/types/omnichannel';
import { useContactsListConfig } from './use-contacts-list-config';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

const listMock = vi.fn();
const exportContactsMock = vi.fn();
vi.mock('@/services/contact-service', () => ({
  contactService: {
    list: (...args: unknown[]) => listMock(...args),
    exportContacts: (...args: unknown[]) => exportContactsMock(...args),
  },
}));

const TAGS: ContactTag[] = [
  {
    id: 'tag-1',
    workspaceId: 'wsp-1',
    name: 'VIP',
    emoji: '⭐',
    color: '#FF5A00',
    description: null,
    contactsCount: 0,
    createdAt: '2026-01-01T00:00:00Z',
  },
];
const FIELDS: ContactField[] = [
  {
    id: 'f-1',
    workspaceId: 'wsp-1',
    key: 'company',
    label: 'Company',
    description: null,
    type: 'text',
    visibility: 'always',
    options: null,
    sortOrder: 0,
    valuesCount: 0,
    createdAt: '2026-01-01T00:00:00Z',
  },
  {
    id: 'f-2',
    workspaceId: 'wsp-1',
    key: 'internalNote',
    label: 'Internal note',
    description: null,
    type: 'text',
    visibility: 'hidden',
    options: null,
    sortOrder: 1,
    valuesCount: 0,
    createdAt: '2026-01-01T00:00:00Z',
  },
];
const MEMBERS: WorkspaceMember[] = [
  { id: 'mem-1', userId: 'u-1', name: 'Ada', email: 'ada@example.com', status: 'ACTIVE', assignedAt: '2026-01-01T00:00:00Z' },
];
const SEGMENTS: ContactSegment[] = [];

function setup() {
  return renderHook(() =>
    useContactsListConfig({
      workspaceId: 'wsp-1',
      segments: SEGMENTS,
      tags: TAGS,
      fields: FIELDS,
      stages: [],
      members: MEMBERS,
      channelTypeOptions: [{ label: 'WHATSAPP', value: 'WHATSAPP' }],
      actions: [],
      onFilterChange: vi.fn(),
    }),
  ).result.current;
}

describe('useContactsListConfig', () => {
  it('exposes only ALWAYS-visible custom fields as filterable, never hidden ones', () => {
    const config = setup();
    const fieldIds = config.filterFields.map((f) => f.field);
    expect(fieldIds).toContain('customFields.company');
    expect(fieldIds).not.toContain('customFields.internalNote');
  });

  it('offers an explicit "Unassigned" option alongside real workspace members on the assignee filter', () => {
    const config = setup();
    const assignee = config.filterFields.find((f) => f.field === 'assignee')!;
    expect(assignee.options).toEqual(
      expect.arrayContaining([
        { label: 'Unassigned', value: 'unassigned' },
        { label: 'Ada', value: 'u-1' },
      ]),
    );
  });

  it('gates create + import by contacts.manage / contacts.import (permission gating)', () => {
    const config = setup();
    expect(config.createPermission).toBe('contacts.manage');
    expect(config.importer).toEqual({
      entityType: 'omnichannel_contacts',
      writePermission: 'contacts.import',
      context: { workspaceId: 'wsp-1' },
    });
  });

  it('fetcher delegates to contactService.list scoped to the resolved workspace', async () => {
    listMock.mockResolvedValue({ data: [], total: 0, page: 0 });
    const config = setup();
    const query = { page: 0, pageSize: 25 };
    await config.fetcher(query);
    expect(listMock).toHaveBeenCalledWith('wsp-1', query);
  });

  it('exporter forwards the current query + picked columns + selection to contactService.exportContacts', async () => {
    exportContactsMock.mockResolvedValue('id,name\n1,Ada');
    const config = setup();
    await config.exporter!(
      { page: 0, pageSize: 25, search: 'ada', sort: { id: 'name', desc: false }, segment: 'seg-1' },
      ['id', 'name'],
      ['cnt-1'],
    );
    expect(exportContactsMock).toHaveBeenCalledWith('wsp-1', {
      columns: ['id', 'name'],
      ids: ['cnt-1'],
      search: 'ada',
      filter: undefined,
      segment: 'seg-1',
      sortBy: 'name',
      sortDir: 'asc',
    });
  });

  it('exports id-first ordering to round-trip via re-import', () => {
    const config = setup();
    expect(config.exportColumns[0].id).toBe('id');
  });
});
