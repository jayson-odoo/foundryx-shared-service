'use client';

import { LoaderCircleIcon } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { useDatetime } from '@/hooks/use-datetime';
import { useBrVersions } from '@/hooks/use-br-versions';

export interface BrVersionsTabProps {
  brId: string;
}

/** Versions tab - the BR's template version history; the STAMPED version is the
 * one this BR renders against forever (AC-BI-16). Data via `useBrVersions`
 * (UI → hook → service). */
export function BrVersionsTab({ brId }: BrVersionsTabProps) {
  const { formatDateTime } = useDatetime();
  const { versions } = useBrVersions(brId);

  if (versions === null) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <LoaderCircleIcon className="size-5 animate-spin" />
      </div>
    );
  }

  if (versions.length === 0) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        No template versions.
      </p>
    );
  }

  return (
    <Card>
      <CardContent className="py-2 divide-y divide-border">
        {versions.map((v) => (
          <div key={v.version} className="flex items-center justify-between gap-3 py-3">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-foreground">v{v.version}</span>
              {v.isStamped && <Badge variant="primary" appearance="light">Stamped</Badge>}
              {v.isActive && <Badge variant="outline" appearance="light">Active</Badge>}
            </div>
            <span className="text-xs text-muted-foreground">
              {formatDateTime(v.createdAt)}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
