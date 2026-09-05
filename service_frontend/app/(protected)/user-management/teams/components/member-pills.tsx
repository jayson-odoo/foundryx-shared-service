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
 * Team members as pills; em-dash when none. Width-aware "+N" popover for the
 * list's Members column, same pattern as `RolesCell` (Users clone, D-A8-2).
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
