'use client';

/**
 * The ONE source of "which contact fields can this workspace filter/segment
 * on" (review round 1, B3) - extracted out of `use-contacts-list-config.tsx`
 * so any other surface that needs to build a condition against contacts
 * (the broadcasts audience Filter builder) reads the SAME whitelist the
 * backend's `contact_filters.CONTACT_FILTER_COLUMNS` + `build_special`
 * actually accepts, instead of hand-rolling a second, drifted list (the
 * broadcasts S0 copy offered `status`/`assignee`/`priority` options the
 * backend rejects with a 422 - a foolproof-UI violation).
 */
import { useMemo } from 'react';
import type { LifecycleStageOption } from '@/hooks/use-contact-lifecycle-stages';
import type { ContactField, ContactTag, WorkspaceMember } from '@/types/omnichannel';
import type { FilterFieldDef, FilterFieldType } from '@/types/resource';

export const CONTACT_PRIORITY_OPTIONS = [
  { label: 'Low', value: 'LOW' },
  { label: 'Medium', value: 'MEDIUM' },
  { label: 'High', value: 'HIGH' },
  { label: 'Urgent', value: 'URGENT' },
];

/** `customFields.<key>` filter type derived from the field's registered type
 *  (AC-CTM-04) - the shell only knows text/enum/date/bool, so `number`/`time`
 *  map to the closest usable operator set (documented deviation, no numeric
 *  range or time-of-day filter in this slice). */
export function customContactFieldFilterType(field: ContactField): FilterFieldType {
  switch (field.type) {
    case 'list':
      return 'enum';
    case 'checkbox':
      return 'bool';
    case 'date':
      return 'date';
    default:
      return 'text';
  }
}

export interface UseContactFilterFieldsParams {
  tags: ContactTag[];
  fields: ContactField[];
  stages: LifecycleStageOption[];
  members: WorkspaceMember[];
  channelTypeOptions: { label: string; value: string }[];
}

/** Every real, backend-accepted contact filter field (system columns +
 *  `customFields.*`) - the Contacts list AND the broadcasts audience Filter
 *  builder both build their field list from this ONE hook. */
export function useContactFilterFields({
  tags,
  fields,
  stages,
  members,
  channelTypeOptions,
}: UseContactFilterFieldsParams): FilterFieldDef[] {
  return useMemo<FilterFieldDef[]>(() => {
    const system: FilterFieldDef[] = [
      { field: 'name', label: 'Name', type: 'text' },
      { field: 'phone', label: 'Phone', type: 'text' },
      { field: 'email', label: 'Email', type: 'text' },
      { field: 'language', label: 'Language', type: 'text' },
      { field: 'countryCode', label: 'Country', type: 'text' },
      { field: 'priority', label: 'Priority', type: 'enum', options: CONTACT_PRIORITY_OPTIONS },
      {
        field: 'assignee',
        label: 'Assignee',
        type: 'enum',
        options: [
          { label: 'Unassigned', value: 'unassigned' },
          ...members.map((m) => ({ label: m.name ?? m.email, value: m.userId })),
        ],
      },
      { field: 'channelType', label: 'Channel', type: 'enum', options: channelTypeOptions },
      {
        field: 'lifecycle',
        label: 'Lifecycle',
        type: 'enum',
        options: stages.map((s) => ({ label: s.label, value: s.key })),
      },
      {
        field: 'tags',
        label: 'Tags',
        type: 'enum',
        options: tags.map((t) => ({ label: `${t.emoji ? `${t.emoji} ` : ''}${t.name}`, value: t.id })),
      },
      { field: 'lastMessageAt', label: 'Last message', type: 'date' },
      { field: 'createdAt', label: 'Created', type: 'date' },
    ];
    const custom: FilterFieldDef[] = fields
      .filter((f) => f.visibility === 'always')
      .map((f) => ({
        field: `customFields.${f.key}`,
        label: f.label,
        type: customContactFieldFilterType(f),
        options: f.type === 'list' ? (f.options ?? []).map((o) => ({ label: o, value: o })) : undefined,
      }));
    return [...system, ...custom];
  }, [members, channelTypeOptions, stages, tags, fields]);
}
