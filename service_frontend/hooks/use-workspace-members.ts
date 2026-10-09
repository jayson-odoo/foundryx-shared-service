'use client';

/** The workspace's members (plan 26) - backs the assignee filter field and the
 *  bulk "Assign" picker (foolproof-UI: only the workspace's own members). */
import { useEffect, useState } from 'react';
import { workspaceService } from '@/services/workspace-service';
import type { WorkspaceMember } from '@/types/omnichannel';

export function useWorkspaceMembers(workspaceId: string | null): { members: WorkspaceMember[]; loading: boolean } {
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setMembers([]);
    if (!workspaceId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    workspaceService
      .getMembers(workspaceId)
      .then((data) => !cancelled && setMembers(data))
      .catch(() => !cancelled && setMembers([]))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  return { members, loading };
}
