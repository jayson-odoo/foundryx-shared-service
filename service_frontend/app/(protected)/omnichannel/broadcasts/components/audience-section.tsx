'use client';

/**
 * Audience section (plan 29, AC-BRD-05) - source is a `SearchSelect` offering
 * Segment / Filter / Selected contacts (mutually exclusive); Segment lists
 * the workspace's saved segments, Filter reuses the Resource-shell filter
 * builder over the SAME whitelisted field list `use-contacts-list-config.tsx`
 * uses (`useContactFilterFields`, review round 1 B3 - the S0 hand-rolled
 * `status`/`assignee`/`priority` copy offered fields the backend's
 * `contact_filters.py` whitelist rejects with a 422), and Selected contacts
 * uses a contacts `MultiSelect` sourced from the real, server-searched A2
 * contact list (review round 1 S2 - `useContactPicker`, replacing the S0
 * `conversationService.listThreads` stand-in capped at 50 rows with no
 * search). The resolved recipient COUNT refreshes whenever the source or its
 * value changes.
 */
import { useState } from 'react';
import { Filter as FilterIcon, Users as UsersIcon } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Button } from '@/components/ui/button';
import { SearchSelect } from '@/components/platform/search-select';
import { MultiSelect } from '@/components/platform/multi-select';
import { FilterBuilder } from '@/components/platform/resource-list/filter-builder';
import { useContactSegments } from '@/hooks/use-contact-segments';
import { useContactTags } from '@/hooks/use-contact-tags';
import { useContactFields } from '@/hooks/use-contact-fields';
import { useContactLifecycleStages } from '@/hooks/use-contact-lifecycle-stages';
import { useWorkspaceMembers } from '@/hooks/use-workspace-members';
import { useContactFilterFields } from '@/hooks/use-contact-filter-fields';
import { useContactPicker } from '@/hooks/use-contact-picker';
import { useChannelTypeOptions } from '@/hooks/use-channel-type-options';
import type { BroadcastAudience } from '@/types/omnichannel';
import { useAudiencePreview } from './use-audience-preview';

const SOURCE_OPTIONS = [
  { label: 'Segment', value: 'segment' },
  { label: 'Filter', value: 'filter' },
  { label: 'Selected contacts', value: 'contacts' },
];

export interface AudienceSectionProps {
  workspaceId: string | null;
  editing: boolean;
  value: BroadcastAudience;
  onChange: (next: BroadcastAudience) => void;
}

export function AudienceSection({ workspaceId, editing, value, onChange }: AudienceSectionProps) {
  const { segments } = useContactSegments(workspaceId);
  const { count } = useAudiencePreview(workspaceId, value);
  const [filterOpen, setFilterOpen] = useState(false);

  const { tags } = useContactTags(workspaceId);
  const { fields } = useContactFields(workspaceId);
  const { stages } = useContactLifecycleStages(workspaceId);
  const { members } = useWorkspaceMembers(workspaceId);
  const channelTypeOptions = useChannelTypeOptions(workspaceId);
  const filterFields = useContactFilterFields({ tags, fields, stages, members, channelTypeOptions });

  const contactIds = value.kind === 'contacts' ? (value.contactIds ?? []) : [];
  const { options: contactOptions, setQuery: setContactQuery } = useContactPicker(workspaceId, contactIds);

  const segmentSummary =
    value.kind === 'segment'
      ? (segments.find((s) => s.id === value.segmentId)?.name ?? value.segmentName ?? null)
      : null;
  const filterSummary =
    value.kind === 'filter' && value.filter ? `${value.filter.rules.length} condition(s)` : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Audience</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 py-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label className="text-sm text-muted-foreground">Source</label>
            <SearchSelect
              options={SOURCE_OPTIONS}
              value={value.kind}
              onChange={(kind) =>
                onChange({ kind: kind as BroadcastAudience['kind'] })
              }
              disabled={!editing}
              ariaLabel="Audience source"
              className="w-full"
            />
          </div>

          {value.kind === 'segment' && (
            <div className="space-y-1.5">
              <label className="text-sm text-muted-foreground">Segment</label>
              <SearchSelect
                options={segments.map((s) => ({ label: s.name, value: s.id }))}
                value={value.segmentId ?? null}
                onChange={(segmentId) => {
                  const seg = segments.find((s) => s.id === segmentId);
                  onChange({ kind: 'segment', segmentId, segmentName: seg?.name });
                }}
                disabled={!editing}
                ariaLabel="Segment"
                className="w-full"
              />
            </div>
          )}

          {value.kind === 'contacts' && (
            <div className="space-y-1.5">
              <label className="text-sm text-muted-foreground">Contacts</label>
              <MultiSelect
                options={contactOptions}
                value={contactIds}
                onChange={(ids) => onChange({ kind: 'contacts', contactIds: ids })}
                onQueryChange={setContactQuery}
                disabled={!editing}
                className="w-full"
              />
            </div>
          )}
        </div>

        {value.kind === 'filter' && (
          <div className="flex items-center gap-2">
            <Popover open={filterOpen} onOpenChange={setFilterOpen}>
              <PopoverTrigger asChild>
                <Button variant="outline" size="sm" disabled={!editing}>
                  <FilterIcon /> {filterSummary ?? 'Build filter'}
                </Button>
              </PopoverTrigger>
              <PopoverContent align="start" className="w-auto p-3">
                <FilterBuilder
                  fields={filterFields}
                  onApply={(group) => onChange({ kind: 'filter', filter: group ?? undefined })}
                  onClose={() => setFilterOpen(false)}
                />
              </PopoverContent>
            </Popover>
          </div>
        )}

        <div className="flex items-center gap-2 rounded-md bg-muted px-3 py-2 text-sm">
          <UsersIcon className="size-4 text-muted-foreground" />
          <span className="font-medium">{count ?? '-'}</span>
          <span className="text-muted-foreground">recipient(s) resolved</span>
          {segmentSummary && <span className="text-muted-foreground">- {segmentSummary}</span>}
        </div>
      </CardContent>
    </Card>
  );
}
