'use client';

import { Badge } from '@/components/ui/badge';
import type { ConnectorSettingSource } from '@/types/connector';
import { SOURCE_LABELS } from './connector-settings-schema';

const VARIANT: Record<ConnectorSettingSource, 'primary' | 'secondary' | 'outline' | 'destructive'> = {
  database: 'primary',
  environment: 'secondary',
  default: 'outline',
  unset: 'outline',
  unreadable: 'destructive',
};

export interface SourceBadgeProps {
  source: ConnectorSettingSource;
}

/** Where an effective setting comes from (database > environment > default). */
export function SourceBadge({ source }: SourceBadgeProps) {
  return (
    <Badge variant={VARIANT[source]} appearance="light" size="sm" data-source={source}>
      {SOURCE_LABELS[source]}
    </Badge>
  );
}
