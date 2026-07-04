'use client';

import type { UseFormReturn } from 'react-hook-form';
import { Activity as ActivityIcon } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import {
  FormControl,
  FormField,
  FormItem,
  FormMessage,
} from '@/components/ui/form';
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
import type { Role, User } from '@/types/user';
import { RolePills } from './role-pills';
import { USER_STATUS_REGISTRY, ASSIGNABLE_STATUSES } from './user-status';
import type { UserFormValues } from './user-schema';

export interface ProfileTabProps {
  form: UseFormReturn<UserFormValues>;
  editing: boolean;
  /** True on the create page (email editable; no record meta yet). */
  creating: boolean;
  /** Editing one's own record — email locked (the /account ceremony owns it). */
  isSelf?: boolean;
  user: User | null;
  roles: Role[];
}

export function ProfileTab({ form, editing, creating, isSelf, user, roles }: ProfileTabProps) {
  const { formatDate, formatDateTime } = useDatetime();
  const roleOptions = roles.map((r) => ({ label: r.name, value: r.id }));
  // Admin instant path (plan sprint-2/04): another user's email is editable;
  // one's OWN email needs the dual-confirmation ceremony (no self-bypass).
  const emailEditable = creating || (editing && !isSelf);

  return (
    <Card>
      <CardContent className="py-1">
        <FormRow label="Full name" required={editing}>
          {editing ? (
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem className="max-w-sm">
                  <FormControl>
                    <Input placeholder="Full name" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            (user?.name ?? '—')
          )}
        </FormRow>

        <FormRow label="Email address" required={emailEditable}>
          {emailEditable ? (
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem className="max-w-sm">
                  <FormControl>
                    <Input type="email" placeholder="name@company.com" {...field} />
                  </FormControl>
                  {!creating && (
                    <p className="text-xs text-muted-foreground">
                      Applies immediately — both the old and new address are notified.
                    </p>
                  )}
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            <div className="flex items-center gap-2">
              <span>{user?.email}</span>
              {user?.emailVerifiedAt ? (
                <Badge variant="success" appearance="light" size="sm">
                  Verified
                </Badge>
              ) : (
                <Badge variant="warning" appearance="light" size="sm">
                  Unverified
                </Badge>
              )}
              {editing && isSelf && (
                <span className="text-xs text-muted-foreground">
                  Change your own email from My Account.
                </span>
              )}
            </div>
          )}
        </FormRow>

        <FormRow label="Roles">
          {editing ? (
            <FormField
              control={form.control}
              name="roleIds"
              render={({ field }) => (
                <FormItem className="max-w-sm">
                  <FormControl>
                    <MultiSelect
                      options={roleOptions}
                      value={field.value}
                      onChange={field.onChange}
                      placeholder="Select roles…"
                      searchPlaceholder="Search roles…"
                    />
                  </FormControl>
                </FormItem>
              )}
            />
          ) : (
            <RolePills roles={user?.roles ?? []} />
          )}
        </FormRow>

        <FormRow label="Status" required={editing && user?.status !== 'INVITED'}>
          {editing && user?.status !== 'INVITED' ? (
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
                      {ASSIGNABLE_STATUSES.map((s) => (
                        <SelectItem key={s} value={s}>
                          {USER_STATUS_REGISTRY[s].label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FormItem>
              )}
            />
          ) : (
            <StatusBadge status={user?.status ?? 'ACTIVE'} registry={USER_STATUS_REGISTRY} />
          )}
        </FormRow>

        {!creating && (
          <>
            <FormRow label="Last sign in">
              {user?.lastSignInAt ? formatDateTime(user.lastSignInAt) : 'Never'}
            </FormRow>
            <FormRow label="Joined">{formatDate(user?.createdAt)}</FormRow>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export function SecurityTab({ user }: { user: User }) {
  const { formatDate, formatDateTime } = useDatetime();
  return (
    <Card>
      <CardContent className="py-1">
        <FormRow label="Email verification">
          {user.emailVerifiedAt ? (
            <span className="flex items-center gap-2">
              <Badge variant="success" appearance="light" size="sm">
                Verified
              </Badge>
              <span className="text-muted-foreground">{formatDate(user.emailVerifiedAt)}</span>
            </span>
          ) : (
            <Badge variant="warning" appearance="light" size="sm">
              Not verified
            </Badge>
          )}
        </FormRow>
        <FormRow label="Password">
          {user.status === 'INVITED' ? (
            <Badge variant="warning" appearance="light" size="sm">
              Pending invite
            </Badge>
          ) : (
            <span className="text-muted-foreground">Set</span>
          )}
        </FormRow>
        <FormRow label="Last sign in">
          {user.lastSignInAt ? formatDateTime(user.lastSignInAt) : 'Never'}
        </FormRow>
        <FormRow label="Manage">
          <span className="text-muted-foreground">
            Use the ⋯ menu (top-right) to reset password or resend verification.
          </span>
        </FormRow>
      </CardContent>
    </Card>
  );
}

export function ActivityTab() {
  return (
    <Card>
      <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
        <ActivityIcon className="size-8 text-muted-foreground" />
        <p className="text-sm font-medium">Activity timeline</p>
        <p className="text-sm text-muted-foreground">
          User activity will appear here once audit logging lands.
        </p>
      </CardContent>
    </Card>
  );
}
