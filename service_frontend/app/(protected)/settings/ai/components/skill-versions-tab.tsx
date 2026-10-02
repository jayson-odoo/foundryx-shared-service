'use client';

import { useCallback, useEffect, useState } from 'react';
import { History, LoaderCircleIcon, RotateCcw } from 'lucide-react';
import { toast } from '@/lib/toast';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ClampedText } from '@/components/platform/clamped-text';
import { useCan } from '@/hooks/use-can';
import { useDatetime } from '@/hooks/use-datetime';
import { aiService } from '@/services/ai-service';
import type { AiSkillVersion } from '@/types/ai';

export interface SkillVersionsTabProps {
  skillId: string;
  /** Bumped by the parent after a save so a new version shows immediately. */
  reloadToken: number;
  onRolledBack: () => void;
}

/**
 * Immutable version history. Rollback is a LABEL MOVE - no content copy, no
 * delete - so the list never loses an entry when you roll back.
 */
export function SkillVersionsTab({ skillId, reloadToken, onRolledBack }: SkillVersionsTabProps) {
  const [versions, setVersions] = useState<AiSkillVersion[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const { formatDateTime } = useDatetime();
  const { can } = useCan();
  const canManage = can('ai_agents.manage');

  const load = useCallback(() => {
    let cancelled = false;
    setIsLoading(true);
    aiService
      .listSkillVersions(skillId)
      .then((rows) => {
        if (!cancelled) setVersions(rows);
      })
      .catch(() => {
        if (!cancelled) setVersions([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [skillId]);

  useEffect(() => load(), [load, reloadToken]);

  const rollback = async (versionId: string) => {
    setBusyId(versionId);
    try {
      await aiService.rollbackSkill(skillId, versionId);
      toast.success('Rolled back - this version is now active.');
      onRolledBack();
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Rollback failed.');
    } finally {
      setBusyId(null);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground">
        <LoaderCircleIcon className="size-5 animate-spin" />
      </div>
    );
  }

  if (versions.length === 0) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">No versions yet.</p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {versions.map((version) => (
        <Card key={version.id}>
          <CardContent className="flex flex-col gap-3 py-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex min-w-0 flex-col gap-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <History className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="text-sm font-medium text-foreground">v{version.version}</span>
                {version.isActive && (
                  <Badge variant="success" appearance="light" size="sm">
                    Active
                  </Badge>
                )}
                <span className="text-xs text-muted-foreground">
                  {version.createdAt ? formatDateTime(version.createdAt) : '-'}
                  {version.createdByName ? ` · ${version.createdByName}` : ''}
                </span>
              </div>
              <ClampedText
                text={version.body}
                lines={3}
                className="font-mono text-xs text-muted-foreground"
              />
            </div>
            {canManage && !version.isActive && (
              <Button
                variant="outline"
                size="sm"
                className="shrink-0 self-start"
                disabled={busyId !== null}
                onClick={() => void rollback(version.id)}
              >
                {busyId === version.id ? (
                  <LoaderCircleIcon className="size-3.5 animate-spin" />
                ) : (
                  <RotateCcw className="size-3.5" />
                )}
                Make active
              </Button>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
