'use client';

/**
 * "Connect a service" with the Foundryx UIUX switch on (gap audit 12, owner
 * answer "Connect on each card"): one card per provider in the catalog, with
 * its icon, its name, a chip for how many are connected (neutral "Not
 * connected" when none) and its own Connect button, which opens the new
 * connection form with that provider already picked (the same deep link a
 * module's settings page uses). The page has no red action of its own; each
 * card's button is local.
 */
import { Button } from '@/components/ui/button';
import type { IntegrationProvider } from '@/types/integration';
import { FxConnectedCountChip, FxProviderIcon } from '@/components/fx/pages/w4-templates/fx-connection-bits';

export function FxIntegrationServices({
  providers,
  counts,
  typeLabel,
  canConnect,
  onConnect,
}: {
  providers: IntegrationProvider[];
  /** Connections per provider key; null while unknown (no chips then). */
  counts: Record<string, number> | null;
  typeLabel: (type: string) => string;
  canConnect: boolean;
  onConnect: (provider: IntegrationProvider) => void;
}) {
  if (providers.length === 0) return null;
  return (
    <section
      aria-label="Connect a service"
      className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"
    >
      {providers.map((p) => (
        <div
          key={p.provider}
          data-fx-service={p.provider}
          className="flex items-center gap-3 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-4 text-(--fx-ink)"
        >
          <FxProviderIcon icon={p.icon} />
          <div className="flex min-w-0 flex-1 flex-col items-start gap-1">
            <span className="font-semibold leading-tight [overflow-wrap:anywhere]">{p.title}</span>
            <span className="text-xs text-(--fx-ink-3)">{typeLabel(p.type)}</span>
            {counts && <FxConnectedCountChip count={counts[p.provider] ?? 0} />}
          </div>
          {canConnect && (
            <Button
              type="button"
              variant="fx-quiet"
              className="h-auto min-h-9 shrink-0 px-4 text-(--fx-ink)"
              aria-label={`Connect ${p.title}`}
              onClick={() => onConnect(p)}
            >
              Connect
            </Button>
          )}
        </div>
      ))}
    </section>
  );
}
