'use client';

import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { OverflowPills } from '@/components/platform/overflow-pills';
import type { Role } from '@/types/user';
import { roleFormPath } from '../../roles/components/paths';

function RoleBadge({ role }: { role: Role }) {
  return (
    <Badge variant="secondary" appearance="light" size="sm">
      {role.name}
    </Badge>
  );
}

/**
 * Roles as pills; em-dash when none. Used in the form (read mode) where each
 * pill links to the role's form view (Users → Roles drill-through). Wraps freely.
 */
export function RolePills({ roles }: { roles: Role[] }) {
  if (!roles.length) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {roles.map((role) => (
        <Link key={role.id} href={roleFormPath(role.id)} className="hover:opacity-80">
          <RoleBadge role={role} />
        </Link>
      ))}
    </div>
  );
}

/**
 * Single-row roles cell for the list: fits as many pills as the column width
 * allows, collapsing the rest into a width-aware "+N" popover (plan 02 review).
 */
export function RolesCell({ roles }: { roles: Role[] }) {
  return (
    <OverflowPills
      items={roles}
      keyFor={(role) => role.id}
      renderPill={(role) => <RoleBadge role={role} />}
    />
  );
}
