'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import type { UseFormReturn } from 'react-hook-form';
import { Info, Loader2, UserPlus, X } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { FormControl, FormField, FormItem, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { FormRow } from '@/components/platform/resource-form';
import { MultiSelect } from '@/components/platform/multi-select';
import { StatusBadge } from '@/components/platform/status-badge';
import { useDatetime } from '@/hooks/use-datetime';
import { keysForResource, mergeResourceGrants } from '@/lib/permissions';
import { roleService } from '@/services/role-service';
import type { PermissionCatalog, PermissionResource } from '@/types/permission';
import type { AssignableUser, RoleDetail, RoleUser } from '@/types/role';
import { userFormPath } from '../../users/components/paths';
import { ASSIGNED_USER_STATUS_REGISTRY } from './assigned-user-status';
import type { RoleFormValues } from './role-schema';

/* ─────────────────────────── Settings tab ─────────────────────────── */

export interface SettingsTabProps {
  form: UseFormReturn<RoleFormValues>;
  editing: boolean;
  role: RoleDetail | null;
  creating: boolean;
}

export function SettingsTab({ form, editing, role, creating }: SettingsTabProps) {
  const { formatDate } = useDatetime();
  return (
    <Card>
      <CardContent className="py-1">
        <FormRow label="Role name" required={editing}>
          {editing ? (
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem className="max-w-sm">
                  <FormControl>
                    <Input placeholder="e.g. Event Manager" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            (role?.name ?? '-')
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
                    <Textarea
                      rows={3}
                      placeholder="What this role is for…"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            <span className={role?.description ? '' : 'text-muted-foreground'}>
              {role?.description || '-'}
            </span>
          )}
        </FormRow>

        <FormRow label="System role">
          {editing ? (
            <FormField
              control={form.control}
              name="isSystem"
              render={({ field }) => (
                <div className="flex items-center gap-3">
                  <Switch checked={field.value} onCheckedChange={field.onChange} />
                  <span className="text-sm text-muted-foreground">
                    {field.value
                      ? 'Protected from deletion. Turn off to allow this role to be deleted.'
                      : 'Not protected - this role can be deleted.'}
                  </span>
                </div>
              )}
            />
          ) : role?.isSystem ? (
            <Badge variant="secondary" appearance="light" size="sm">
              System role
            </Badge>
          ) : (
            <span className="text-muted-foreground">Custom role</span>
          )}
        </FormRow>

        {!creating && role && <FormRow label="Created">{formatDate(role.createdAt)}</FormRow>}
      </CardContent>
    </Card>
  );
}

/* ────────────────────────── Permissions tab ───────────────────────── */

interface PermissionResourceRowProps {
  resource: PermissionResource;
  editing: boolean;
  value: string[];
  onChange: (next: string[]) => void;
}

/**
 * One resource row: an actions MultiSelect (edit) or granted-action pills (read).
 * The implied-read rule (any write ⇒ read, locked) is applied in `onChange` via
 * `mergeResourceGrants`, so clearing `read` while a write is selected re-adds it.
 */
function PermissionResourceRow({ resource, editing, value, onChange }: PermissionResourceRowProps) {
  const options = resource.actions.map((a) => ({ label: a.actionLabel, value: a.key }));
  const selected = keysForResource(value, resource.resource);
  const labelOf = (key: string) => resource.actions.find((a) => a.key === key)?.actionLabel ?? key;

  return (
    <div className="grid grid-cols-1 items-center gap-2 border-b border-border py-3 last:border-0 sm:grid-cols-[220px_1fr] sm:gap-4">
      <span className="text-sm font-medium text-foreground">{resource.resourceLabel}</span>
      {editing ? (
        <MultiSelect
          options={options}
          value={selected}
          onChange={(next) => onChange(mergeResourceGrants(value, resource.resource, next))}
          placeholder="No access"
          searchPlaceholder="Search actions…"
          size="sm"
          className="max-w-sm"
        />
      ) : selected.length ? (
        <div className="flex flex-wrap items-center gap-1">
          {selected.map((key) => (
            <Badge key={key} variant="secondary" appearance="light" size="sm">
              {labelOf(key)}
            </Badge>
          ))}
        </div>
      ) : (
        <span className="text-sm text-muted-foreground">No access</span>
      )}
    </div>
  );
}

export interface PermissionsTabProps {
  form: UseFormReturn<RoleFormValues>;
  editing: boolean;
  catalog: PermissionCatalog;
}

export function PermissionsTab({ form, editing, catalog }: PermissionsTabProps) {
  // Group resources by owning module for section headers.
  const groups = useMemo(() => {
    const byModule = new Map<string, PermissionResource[]>();
    for (const res of catalog) {
      const list = byModule.get(res.module) ?? [];
      list.push(res);
      byModule.set(res.module, list);
    }
    return Array.from(byModule.entries()).map(([module, resources]) => ({ module, resources }));
  }, [catalog]);

  return (
    <FormField
      control={form.control}
      name="permissionKeys"
      render={({ field }) => (
        <FormItem>
          <div className="flex flex-col gap-4">
            {groups.map((group) => (
              <Card key={group.module}>
                <CardContent className="py-1">
                  <p className="border-b border-border py-2.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {group.module}
                  </p>
                  {group.resources.map((resource) => (
                    <PermissionResourceRow
                      key={resource.resource}
                      resource={resource}
                      editing={editing}
                      value={field.value}
                      onChange={field.onChange}
                    />
                  ))}
                </CardContent>
              </Card>
            ))}
          </div>
        </FormItem>
      )}
    />
  );
}

/* ───────────────────────── Assigned Users tab ─────────────────────── */

function Initials({ name, email }: { name: string | null; email: string }) {
  const src = (name || email).trim();
  const initials = src.slice(0, 2).toUpperCase();
  return (
    <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium text-muted-foreground">
      {initials}
    </span>
  );
}

export interface AssignedUsersTabProps {
  roleId: string | null;
  creating: boolean;
}

export function AssignedUsersTab({ roleId, creating }: AssignedUsersTabProps) {
  const { formatDateTime } = useDatetime();
  const [search, setSearch] = useState('');
  const [assigned, setAssigned] = useState<RoleUser[]>([]);
  const [assignable, setAssignable] = useState<AssignableUser[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    if (!roleId) return;
    setLoading(true);
    try {
      const [a, b] = await Promise.all([
        roleService.getAssignedUsers(roleId, search),
        roleService.listAssignable(roleId),
      ]);
      setAssigned(a);
      setAssignable(b);
    } finally {
      setLoading(false);
    }
  }, [roleId, search]);

  useEffect(() => {
    if (!creating) void reload();
  }, [creating, reload]);

  if (creating || !roleId) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
          <Info className="size-8 text-muted-foreground" />
          <p className="text-sm font-medium">Assign users after creating the role</p>
          <p className="text-sm text-muted-foreground">
            Save this role first - you can then assign users to it from this tab.
          </p>
        </CardContent>
      </Card>
    );
  }

  const assignableOptions = assignable.map((u) => ({
    label: `${u.name ?? u.email} · ${u.email}`,
    value: u.id,
  }));

  async function assign() {
    if (!roleId || !picked.length) return;
    setBusy(true);
    try {
      await roleService.assignUsers(roleId, picked);
      toast.success(`Assigned ${picked.length} user(s).`);
      setPicked([]);
      await reload();
    } finally {
      setBusy(false);
    }
  }

  async function remove(userId: string) {
    if (!roleId) return;
    await roleService.removeUser(roleId, userId);
    toast.success('User unassigned.');
    await reload();
  }

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 py-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="w-full max-w-xs">
            <Input
              placeholder="Search assigned users…"
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
              emptyText="No more users to assign."
              size="sm"
              className="w-64"
            />
            <Button variant="primary" size="sm" onClick={assign} disabled={busy || !picked.length}>
              <UserPlus />
              Assign user
            </Button>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            <Loader2 className="size-5 animate-spin" />
          </div>
        ) : assigned.length === 0 ? (
          <div className="flex flex-col items-center gap-1 py-12 text-center">
            <p className="text-sm font-medium">No users assigned</p>
            <p className="text-sm text-muted-foreground">
              Use the picker above to assign users to this role.
            </p>
          </div>
        ) : (
          <div className="flex flex-col">
            <div className="grid grid-cols-[1fr_140px_120px_40px] items-center gap-3 border-b border-border py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <span>User</span>
              <span>Joined</span>
              <span>Status</span>
              <span />
            </div>
            {assigned.map((u) => (
              <div
                key={u.id}
                className="grid grid-cols-[1fr_140px_120px_40px] items-center gap-3 border-b border-border py-2.5 last:border-0"
              >
                <Link href={userFormPath(u.id)} className="group flex items-center gap-2.5">
                  <Initials name={u.name} email={u.email} />
                  <div className="flex flex-col">
                    <span className="text-sm font-medium text-foreground leading-tight transition-colors group-hover:text-primary">
                      {u.name ?? '-'}
                    </span>
                    <span className="text-xs text-muted-foreground">{u.email}</span>
                  </div>
                </Link>
                <span className="text-sm text-muted-foreground">{formatDateTime(u.assignedAt)}</span>
                <StatusBadge status={u.status} registry={ASSIGNED_USER_STATUS_REGISTRY} />
                <Button
                  variant="ghost"
                  size="sm"
                  mode="icon"
                  aria-label={`Unassign ${u.name ?? u.email}`}
                  onClick={() => void remove(u.id)}
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
