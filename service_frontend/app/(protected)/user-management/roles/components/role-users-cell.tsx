'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Loader2, Users as UsersIcon } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { StatusBadge } from '@/components/platform/status-badge';
import { roleService } from '@/services/role-service';
import type { RoleUser } from '@/types/role';
import { userFormPath } from '../../users/components/paths';
import { ASSIGNED_USER_STATUS_REGISTRY } from './assigned-user-status';

const stop = (e: React.MouseEvent) => e.stopPropagation();

function Initials({ name, email }: { name: string | null; email: string }) {
  const initials = (name || email).trim().slice(0, 2).toUpperCase();
  return (
    <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-[10px] font-medium text-muted-foreground">
      {initials}
    </span>
  );
}

/**
 * Roles-list "Users" cell: shows the count and, on click, expands an inline
 * popover listing the assigned users - each name links to that user's form view
 * (the Roles → Users drill-through, plan 03 follow-up).
 */
export function RoleUsersCell({ roleId, count }: { roleId: string; count: number }) {
  const [open, setOpen] = useState(false);
  const [users, setUsers] = useState<RoleUser[] | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setUsers(await roleService.getAssignedUsers(roleId));
    } finally {
      setLoading(false);
    }
  }

  if (count === 0) {
    return (
      <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <UsersIcon className="size-3.5" />0
      </span>
    );
  }

  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (o && users === null) void load();
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          onClick={stop}
          className="flex items-center gap-1.5 text-sm text-foreground hover:text-primary hover:underline"
        >
          <UsersIcon className="size-3.5" />
          {count}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-0" onClick={stop}>
        <div className="border-b border-border px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Assigned users
        </div>
        {loading || users === null ? (
          <div className="flex items-center justify-center py-6 text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
          </div>
        ) : (
          <div className="max-h-72 overflow-y-auto py-1">
            {users.map((u) => (
              <Link
                key={u.id}
                href={userFormPath(u.id)}
                className="flex items-center gap-2.5 px-3 py-2 hover:bg-accent"
              >
                <Initials name={u.name} email={u.email} />
                <div className="flex min-w-0 flex-col">
                  <span className="truncate text-sm font-medium text-foreground leading-tight">
                    {u.name ?? '-'}
                  </span>
                  <span className="truncate text-xs text-muted-foreground">{u.email}</span>
                </div>
                <span className="ms-auto">
                  <StatusBadge status={u.status} registry={ASSIGNED_USER_STATUS_REGISTRY} size="sm" />
                </span>
              </Link>
            ))}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
