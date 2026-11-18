'use client';

/**
 * A connection's card with the Foundryx UIUX switch on (gap audit 12,
 * "Connected services"): the provider's icon, the connection's name, the
 * provider and type, its state as a status chip and when it was last tested.
 * - Needs attention (Error): the last error in plain words and Reconnect as
 *   the card's one button, which opens the connection for editing (the same
 *   page the row's Edit opens; nothing is sent until it is saved).
 * - Test connection (the card's More menu): its result shows on the card.
 */
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useDatetime } from '@/hooks/use-datetime';
import type { Connection } from '@/types/integration';
import {
  FxConnectionChip,
  FxProviderIcon,
  FxTestResultLine,
} from '@/components/fx/pages/w4-templates/fx-connection-bits';
import { useConnectionTestResult } from './connection-test-results';

export interface FxConnectionCardProps {
  connection: Connection;
  providerTitle: string;
  providerIcon: string | null;
  typeLabel: string;
  canReconnect: boolean;
  onReconnect: (connection: Connection) => void;
}

export function FxConnectionCard({
  connection,
  providerTitle,
  providerIcon,
  typeLabel,
  canReconnect,
  onReconnect,
}: FxConnectionCardProps) {
  const { formatRelative, formatDateTime } = useDatetime();
  const result = useConnectionTestResult(connection.id);
  const needsAttention = connection.status === 'ERROR';

  return (
    <div className="flex flex-col gap-3" data-fx-connection-card={connection.id}>
      <div className="flex items-center gap-3 pe-6">
        <FxProviderIcon icon={providerIcon} />
        <div className="flex min-w-0 flex-col">
          <span className="flex flex-wrap items-center gap-2 font-semibold leading-tight text-(--fx-ink) [overflow-wrap:anywhere]">
            {connection.name}
            {connection.type === 'storage' && connection.isActive && (
              <Badge variant="success" appearance="light" size="sm">
                Active
              </Badge>
            )}
          </span>
          <span className="text-sm text-(--fx-ink-3)">
            {providerTitle} · {typeLabel}
          </span>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <FxConnectionChip status={connection.status} />
        <span
          className="text-sm text-(--fx-ink-3)"
          title={connection.lastTestedAt ? formatDateTime(connection.lastTestedAt) : undefined}
        >
          {connection.lastTestedAt ? `Last tested ${formatRelative(connection.lastTestedAt)}` : 'Never tested'}
        </span>
      </div>
      {needsAttention && connection.lastError && (
        <p className="text-sm text-(--fx-warn-ink) [overflow-wrap:anywhere]">{connection.lastError}</p>
      )}
      <FxTestResultLine result={result} />
      {needsAttention && canReconnect && (
        <div
          role="presentation"
          className="flex"
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
        >
          <Button
            type="button"
            variant="fx-quiet"
            className="h-auto min-h-9 px-4 text-(--fx-ink)"
            aria-label={`Reconnect ${connection.name}`}
            onClick={() => onReconnect(connection)}
          >
            Reconnect
          </Button>
        </div>
      )}
    </div>
  );
}
