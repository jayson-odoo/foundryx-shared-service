'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import type { UseFormReturn } from 'react-hook-form';
import { Info, Loader2, MessageCircle, UserPlus, X } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { FormControl, FormField, FormItem, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { FormRow } from '@/components/platform/resource-form';
import { MultiSelect } from '@/components/platform/multi-select';
import { StatusBadge } from '@/components/platform/status-badge';
import { useDatetime } from '@/hooks/use-datetime';
import { workspaceService } from '@/services/workspace-service';
import { channelService } from '@/services/channel-service';
import type { Channel, MemberCandidate, Workspace, WorkspaceMember } from '@/types/omnichannel';
import { USER_STATUS_REGISTRY } from '../../../../user-management/users/components/user-status';
import { userFormPath } from '../../../../user-management/users/components/paths';
import { CHANNEL_STATUS_REGISTRY } from '../../channels/components/channel-status';
import { channelFormPath } from '../../channels/components/paths';
import { WORKSPACE_STATUS_REGISTRY, WORKSPACE_STATUSES } from './workspace-status';
import type { WorkspaceFormValues } from './workspace-schema';

function Initials({ name, email }: { name: string | null; email: string }) {
  const initials = (name || email).trim().slice(0, 2).toUpperCase();
  return (
    <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium text-muted-foreground">
      {initials}
    </span>
  );
}

/* ───────────────────────────── Settings tab ───────────────────────────── */

export interface WorkspaceTabProps {
  form: UseFormReturn<WorkspaceFormValues>;
  editing: boolean;
  creating: boolean;
  workspace: Workspace | null;
}

export function SettingsTab({ form, editing, creating, workspace }: WorkspaceTabProps) {
  const { formatDate } = useDatetime();
  return (
    <Card>
      <CardContent className="py-1">
        <FormRow label="Workspace name" required={editing}>
          {editing ? (
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem className="max-w-sm">
                  <FormControl>
                    <Input placeholder="e.g. Sales & Support" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            <div className="flex items-center gap-2">
              <span>{workspace?.name ?? '—'}</span>
              {workspace?.isDefault && (
                <Badge variant="secondary" appearance="light" size="sm">
                  Default
                </Badge>
              )}
            </div>
          )}
        </FormRow>

        <FormRow label="Status" required={editing}>
          {editing ? (
            <FormField
              control={form.control}
              name="status"
              render={({ field }) => (
                <FormItem className="max-w-[200px]">
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {WORKSPACE_STATUSES.map((s) => (
                        <SelectItem key={s} value={s}>
                          {WORKSPACE_STATUS_REGISTRY[s].label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FormItem>
              )}
            />
          ) : (
            <StatusBadge
              status={workspace?.status ?? 'ACTIVE'}
              registry={WORKSPACE_STATUS_REGISTRY}
            />
          )}
        </FormRow>

        {!creating && (
          <FormRow label="Created">{workspace ? formatDate(workspace.createdAt) : '—'}</FormRow>
        )}
      </CardContent>
    </Card>
  );
}

/* ───────────────────────────── Channels tab ───────────────────────────── */

export function ChannelsTab({ workspaceId, creating }: { workspaceId: string | null; creating: boolean }) {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (creating || !workspaceId) return;
    setLoading(true);
    channelService
      .listByWorkspace(workspaceId)
      .then(setChannels)
      .catch(() => setChannels([]))
      .finally(() => setLoading(false));
  }, [workspaceId, creating]);

  if (creating || !workspaceId) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
          <Info className="size-8 text-muted-foreground" />
          <p className="text-sm font-medium">Connect channels after creating the workspace</p>
          <p className="text-sm text-muted-foreground">
            Save this workspace first, then connect a channel to it from the Channels page.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="py-4">
        {loading ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            <Loader2 className="size-5 animate-spin" />
          </div>
        ) : channels.length === 0 ? (
          <div className="flex flex-col items-center gap-1 py-12 text-center">
            <p className="text-sm font-medium">No channels connected</p>
            <p className="text-sm text-muted-foreground">
              Connect a WhatsApp number to this workspace from the Channels page.
            </p>
          </div>
        ) : (
          <div className="flex flex-col">
            <div className="grid grid-cols-[1fr_180px_120px] items-center gap-3 border-b border-border py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <span>Channel</span>
              <span>Phone Number</span>
              <span>Status</span>
            </div>
            {channels.map((c) => (
              <Link
                key={c.id}
                href={channelFormPath(c.id)}
                className="group grid grid-cols-[1fr_180px_120px] items-center gap-3 border-b border-border py-2.5 last:border-0"
              >
                <span className="flex items-center gap-2.5">
                  <span className="flex size-8 items-center justify-center rounded-md bg-[#25D366]/10 text-[#25D366]">
                    <MessageCircle className="size-4" />
                  </span>
                  <span className="text-sm font-medium text-foreground transition-colors group-hover:text-primary">
                    {c.name}
                  </span>
                </span>
                <span className="text-sm text-muted-foreground">{c.displayPhoneNumber ?? '—'}</span>
                <StatusBadge status={c.status} registry={CHANNEL_STATUS_REGISTRY} />
              </Link>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/* ───────────────────────────── Members tab ───────────────────────────── */

export function MembersTab({ workspaceId, creating }: { workspaceId: string | null; creating: boolean }) {
  const { formatDateTime } = useDatetime();
  const [search, setSearch] = useState('');
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [assignable, setAssignable] = useState<MemberCandidate[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    if (!workspaceId) return;
    setLoading(true);
    try {
      const [m, a] = await Promise.all([
        workspaceService.getMembers(workspaceId, search),
        workspaceService.listAssignable(workspaceId),
      ]);
      setMembers(m);
      setAssignable(a);
    } finally {
      setLoading(false);
    }
  }, [workspaceId, search]);

  useEffect(() => {
    if (!creating) void reload();
  }, [creating, reload]);

  if (creating || !workspaceId) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
          <Info className="size-8 text-muted-foreground" />
          <p className="text-sm font-medium">Add members after creating the workspace</p>
          <p className="text-sm text-muted-foreground">
            Save this workspace first — you can then add members from this tab.
          </p>
        </CardContent>
      </Card>
    );
  }

  const assignableOptions = assignable.map((u) => ({
    label: `${u.name ?? u.email} · ${u.email}`,
    value: u.userId,
  }));

  async function assign() {
    if (!workspaceId || !picked.length) return;
    setBusy(true);
    try {
      await workspaceService.assignMembers(workspaceId, picked);
      toast.success(`Added ${picked.length} member(s).`);
      setPicked([]);
      await reload();
    } finally {
      setBusy(false);
    }
  }

  async function remove(userId: string) {
    if (!workspaceId) return;
    await workspaceService.removeMember(workspaceId, userId);
    toast.success('Member removed.');
    await reload();
  }

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 py-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="w-full max-w-xs">
            <Input
              placeholder="Search members…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-2">
            <MultiSelect
              options={assignableOptions}
              value={picked}
              onChange={setPicked}
              placeholder="Select users…"
              searchPlaceholder="Search users…"
              emptyText="No more users to add."
              size="sm"
              className="w-64"
            />
            <Button variant="primary" size="sm" onClick={assign} disabled={busy || !picked.length}>
              <UserPlus />
              Add member
            </Button>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            <Loader2 className="size-5 animate-spin" />
          </div>
        ) : members.length === 0 ? (
          <div className="flex flex-col items-center gap-1 py-12 text-center">
            <p className="text-sm font-medium">No members yet</p>
            <p className="text-sm text-muted-foreground">
              Use the picker above to add members to this workspace.
            </p>
          </div>
        ) : (
          <div className="flex flex-col">
            <div className="grid grid-cols-[1fr_160px_120px_40px] items-center gap-3 border-b border-border py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <span>Member</span>
              <span>Added</span>
              <span>Status</span>
              <span />
            </div>
            {members.map((m) => (
              <div
                key={m.id}
                className="grid grid-cols-[1fr_160px_120px_40px] items-center gap-3 border-b border-border py-2.5 last:border-0"
              >
                <Link href={userFormPath(m.userId)} className="group flex items-center gap-2.5">
                  <Initials name={m.name} email={m.email} />
                  <div className="flex flex-col">
                    <span className="text-sm font-medium text-foreground leading-tight transition-colors group-hover:text-primary">
                      {m.name ?? '—'}
                    </span>
                    <span className="text-xs text-muted-foreground">{m.email}</span>
                  </div>
                </Link>
                <span className="text-sm text-muted-foreground">{formatDateTime(m.assignedAt)}</span>
                <StatusBadge status={m.status} registry={USER_STATUS_REGISTRY} />
                <Button
                  variant="ghost"
                  size="sm"
                  mode="icon"
                  aria-label={`Remove ${m.name ?? m.email}`}
                  onClick={() => void remove(m.userId)}
                >
                  <X />
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
