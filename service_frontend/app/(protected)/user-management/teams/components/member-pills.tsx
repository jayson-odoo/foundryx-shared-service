'use client';

import { Crown } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { OverflowPills } from '@/components/platform/overflow-pills';
import type { TeamMemberRef } from '@/types/team';

function MemberBadge({ member }: { member: TeamMemberRef }) {
  return (
    <Badge variant="secondary" appearance="light" size="sm">
      {member.role === 'lead' && <Crown className="size-3" aria-hidden />}
      {member.name}
    </Badge>
  );
}

/**
 * Team members as pills for the Teams list's Members column; a hyphen
 * placeholder when there are none. Width-aware "+N" popover via
 * `OverflowPills`, the same pattern the Users list's `RolesCell`
 * (`role-pills.tsx`) uses for its Roles column.
 */
export function MemberPills({ members }: { members: TeamMemberRef[] }) {
  if (!members.length) return <span className="text-muted-foreground">-</span>;
  return (
    <OverflowPills
      items={members}
      keyFor={(m) => m.userId}
      renderPill={(m) => <MemberBadge member={m} />}
    />
  );
}
