'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { Users as UsersIcon } from 'lucide-react';
import { toast } from '@/lib/toast';
import { ApiError } from '@/lib/api-client';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { ListQuery } from '@/types/resource';
import { teamService } from '@/services/team-service';
import { userService } from '@/services/user-service';
import type { Team, TeamMemberInput } from '@/types/team';
import type { User } from '@/types/user';
import { TeamDetailsTab } from './team-form-fields';
import { useTeamActions } from './use-team-actions';
import { teamFormHref, teamFormPath, teamsListPath } from './paths';
import { teamFormSchema, type TeamFormValues } from './team-schema';

function toFormValues(team: Team | null): TeamFormValues {
  if (!team) return { name: '', description: '', isActive: true, memberIds: [], leadIds: [] };
  return {
    name: team.name,
    description: team.description ?? '',
    isActive: team.isActive,
    memberIds: team.members.map((m) => m.userId),
    leadIds: team.members.filter((m) => m.role === 'lead').map((m) => m.userId),
  };
}

function toMembersPayload(values: TeamFormValues): TeamMemberInput[] {
  return values.memberIds.map((userId) => ({
    userId,
    role: values.leadIds.includes(userId) ? 'lead' : 'member',
  }));
}

export interface UseTeamFormResult {
  config: ResourceFormConfig<Team> | null;
  form: UseFormReturn<TeamFormValues>;
  isLoading: boolean;
  notFound: boolean;
  loadError: Error | null;
}

/** Loads the record + tenant users, wires RHF, and assembles the form config
 * (Users clone, D-A8-2). */
export function useTeamForm(teamId: string | undefined, initialEditing: boolean): UseTeamFormResult {
  const router = useRouter();
  const actions = useTeamActions();
  const creating = !teamId;

  const [team, setTeam] = useState<Team | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [loadError, setLoadError] = useState<Error | null>(null);

  const form = useForm<TeamFormValues>({
    mode: 'onTouched',
    resolver: zodResolver(teamFormSchema),
    defaultValues: toFormValues(null),
  });

  // Load the tenant's users once - the Members/Leads picker's option set.
  useEffect(() => {
    userService
      .list({ page: 0, pageSize: 200, sort: null })
      .then((res) => setUsers(res.data))
      .catch(() => setUsers([]));
  }, []);

  useEffect(() => {
    let active = true;
    if (creating) {
      setTeam(null);
      form.reset(toFormValues(null));
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    setNotFound(false);
    setLoadError(null);
    teamService
      .get(teamId)
      .then((t) => {
        if (!active) return;
        setTeam(t);
        form.reset(toFormValues(t));
        setNotFound(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        } else {
          setLoadError(err instanceof Error ? err : new Error('Failed to load team.'));
        }
      })
      .finally(() => active && setIsLoading(false));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teamId, creating]);

  const fetchRecordAt = useCallback(
    (query: ListQuery, index: number) =>
      teamService.getAt(query, index).then((r) => ({
        recordId: r.team?.id ?? null,
        total: r.total,
      })),
    [],
  );
  const buildRecordHref = useCallback(
    (recordId: string, ctx: string, index: number) => teamFormHref(recordId, { ctx, index }),
    [],
  );

  const config = useMemo<ResourceFormConfig<Team> | null>(() => {
    if (isLoading || notFound || loadError) return null;

    const onSave = async (): Promise<boolean> => {
      let ok = false;
      await form.handleSubmit(async (values) => {
        const payload = {
          name: values.name,
          description: values.description || null,
          isActive: values.isActive,
          members: toMembersPayload(values),
        };
        if (creating) {
          const created = await teamService.create(payload);
          toast.success('Team created.');
          router.push(teamFormPath(created.id));
        } else {
          const updated = await teamService.update(teamId, payload);
          setTeam(updated);
          form.reset(toFormValues(updated));
          toast.success('Team updated.');
        }
        ok = true;
      })();
      return ok;
    };

    const onCancel = () => {
      if (creating) router.push(teamsListPath);
      else form.reset(toFormValues(team));
    };

    const tabs = [
      {
        id: 'details',
        label: 'Details',
        icon: UsersIcon,
        render: ({ editing }: { editing: boolean }) => (
          <TeamDetailsTab form={form} editing={editing} creating={creating} team={team} users={users} />
        ),
      },
    ];

    return {
      breadcrumb: [
        { label: 'Home', href: '/' },
        { label: 'User Management', href: teamsListPath },
        { label: 'Teams', href: teamsListPath },
        { label: creating ? 'New team' : (team?.name ?? 'Team') },
      ],
      backHref: teamsListPath,
      backLabel: 'Back to teams',
      title: creating ? 'New team' : (team?.name ?? 'Team'),
      subtitle: creating ? 'Group tenant users for assignment' : (team?.description ?? undefined),
      tabs,
      actions,
      actionRows: team ? [team] : [],
      editable: !creating,
      editPermission: 'teams.manage',
      initialEditing: creating ? true : initialEditing,
      isDirty: form.formState.isDirty,
      onSave,
      onCancel,
      recordNav: creating ? undefined : { fetchAt: fetchRecordAt, buildHref: buildRecordHref },
    };
  }, [
    isLoading,
    notFound,
    loadError,
    creating,
    team,
    users,
    actions,
    form,
    initialEditing,
    teamId,
    router,
    fetchRecordAt,
    buildRecordHref,
  ]);

  return { config, form, isLoading, notFound, loadError };
}
