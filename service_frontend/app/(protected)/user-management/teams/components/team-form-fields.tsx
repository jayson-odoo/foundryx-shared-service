'use client';

import type { UseFormReturn } from 'react-hook-form';
import { Card, CardContent } from '@/components/ui/card';
import {
  FormControl,
  FormField,
  FormItem,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { FormRow } from '@/components/platform/resource-form';
import { MultiSelect } from '@/components/platform/multi-select';
import { StatusBadge } from '@/components/platform/status-badge';
import { useDatetime } from '@/hooks/use-datetime';
import type { User } from '@/types/user';
import type { Team } from '@/types/team';
import { MemberPills } from './member-pills';
import { TEAM_STATUS_REGISTRY, teamStatus } from './team-status';
import type { TeamFormValues } from './team-schema';

export interface TeamDetailsTabProps {
  form: UseFormReturn<TeamFormValues>;
  editing: boolean;
  creating: boolean;
  team: Team | null;
  /** Every tenant user - the Members picker's option set (D-A8-2). */
  users: User[];
}

export function TeamDetailsTab({ form, editing, creating, team, users }: TeamDetailsTabProps) {
  const { formatDate } = useDatetime();
  const memberIds = form.watch('memberIds');
  const memberOptions = users.map((u) => ({ label: u.name ?? u.email, value: u.id }));
  // Foolproof-UI (AC-TEM-40): the Leads picker only ever offers users
  // currently selected as Members - never an invalid, non-member lead.
  const leadOptions = memberOptions.filter((o) => memberIds.includes(o.value));

  return (
    <Card>
      <CardContent className="py-1">
        <FormRow label="Name" required={editing}>
          {editing ? (
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem className="max-w-sm">
                  <FormControl>
                    <Input placeholder="Team name" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            (team?.name ?? '-')
          )}
        </FormRow>

        <FormRow label="Description">
          {editing ? (
            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem className="max-w-md">
                  <FormControl>
                    <Textarea placeholder="What this team handles" rows={3} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            (team?.description ?? '-')
          )}
        </FormRow>

        <FormRow label="Members">
          {editing ? (
            <FormField
              control={form.control}
              name="memberIds"
              render={({ field }) => (
                <FormItem className="max-w-sm">
                  <FormControl>
                    <MultiSelect
                      options={memberOptions}
                      value={field.value}
                      onChange={(next) => {
                        field.onChange(next);
                        // Removing a member removes them from Leads too.
                        const leads = form.getValues('leadIds');
                        const kept = leads.filter((id) => next.includes(id));
                        if (kept.length !== leads.length) form.setValue('leadIds', kept, { shouldDirty: true });
                      }}
                      placeholder="Select members…"
                      searchPlaceholder="Search users…"
                    />
                  </FormControl>
                </FormItem>
              )}
            />
          ) : (
            <MemberPills members={team?.members ?? []} />
          )}
        </FormRow>

        <FormRow label="Leads">
          {editing ? (
            <FormField
              control={form.control}
              name="leadIds"
              render={({ field }) => (
                <FormItem className="max-w-sm">
                  <FormControl>
                    <MultiSelect
                      options={leadOptions}
                      value={field.value}
                      onChange={field.onChange}
                      placeholder={
                        leadOptions.length ? 'Select leads…' : 'Add members first'
                      }
                      searchPlaceholder="Search members…"
                      disabled={leadOptions.length === 0}
                    />
                  </FormControl>
                </FormItem>
              )}
            />
          ) : (
            <MemberPills members={(team?.members ?? []).filter((m) => m.role === 'lead')} />
          )}
        </FormRow>

        <FormRow label="Status">
          {editing ? (
            <FormField
              control={form.control}
              name="isActive"
              render={({ field }) => (
                <FormItem>
                  <FormControl>
                    <div className="flex items-center gap-2">
                      <Switch checked={field.value} onCheckedChange={field.onChange} />
                      <span className="text-sm text-muted-foreground">
                        {field.value ? 'Active' : 'Inactive'}
                      </span>
                    </div>
                  </FormControl>
                </FormItem>
              )}
            />
          ) : (
            <StatusBadge
              status={teamStatus(team?.isActive ?? true)}
              registry={TEAM_STATUS_REGISTRY}
            />
          )}
        </FormRow>

        {!creating && (
          <>
            <FormRow label="Created">{formatDate(team?.createdAt)}</FormRow>
            <FormRow label="Updated">{formatDate(team?.updatedAt)}</FormRow>
          </>
        )}
      </CardContent>
    </Card>
  );
}
