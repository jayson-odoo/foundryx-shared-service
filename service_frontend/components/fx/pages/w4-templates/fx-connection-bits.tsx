'use client';

/**
 * Integrations with the Foundryx UIUX switch on (slice W4-TEMPLATES, gap
 * audit 12 "Connected services"): the status chip, the provider's icon and the
 * Test connection result line, shared by the service cards, the connection
 * cards and the record's Health card.
 */
import type { ComponentType, SVGProps } from 'react';
import {
  Bot,
  Calendar,
  Cloud,
  CreditCard,
  Database,
  Gem,
  Landmark,
  Loader2,
  Mail,
  Plug,
  Sparkles,
  Video,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useDatetime } from '@/hooks/use-datetime';
import type { ConnectionStatus, TestConnectionResult } from '@/types/integration';

type ConnectionTestState = TestConnectionResult | 'testing';

const CHIP: Record<ConnectionStatus | 'NONE', string> = {
  ACTIVE: 'bg-(--fx-ok-bg) text-(--fx-ok-ink)',
  UNVERIFIED: 'bg-(--fx-info-bg) text-(--fx-info-ink)',
  ERROR: 'bg-(--fx-warn-bg) text-(--fx-warn-ink)',
  NONE: 'bg-(--fx-chip) text-(--fx-chip-ink)',
};

const CHIP_LABEL: Record<ConnectionStatus, string> = {
  ACTIVE: 'Connected',
  UNVERIFIED: 'Not tested yet',
  ERROR: 'Needs attention',
};

/** The playbook's status chip for a connection's state. */
export function FxConnectionChip({ status, className }: { status: ConnectionStatus; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex h-6 items-center rounded-(--fx-r-pill) px-2.5 text-xs font-semibold whitespace-nowrap',
        CHIP[status],
        className,
      )}
    >
      {CHIP_LABEL[status]}
    </span>
  );
}

/** A small count chip: "2 connected" on the ok set, "Not connected" neutral. */
export function FxConnectedCountChip({ count }: { count: number }) {
  return (
    <span
      className={cn(
        'inline-flex h-5 items-center rounded-(--fx-r-pill) px-2 text-xs font-semibold whitespace-nowrap',
        count > 0 ? CHIP.ACTIVE : CHIP.NONE,
      )}
    >
      {count > 0 ? `${count} connected` : 'Not connected'}
    </span>
  );
}

const PROVIDER_ICONS: Record<string, ComponentType<SVGProps<SVGSVGElement>>> = {
  mail: Mail,
  landmark: Landmark,
  bot: Bot,
  database: Database,
  cloud: Cloud,
  gem: Gem,
  sparkles: Sparkles,
  'credit-card': CreditCard,
  calendar: Calendar,
  video: Video,
};

/** The provider's own icon (its catalog key), a plug when it has none. */
export function FxProviderIcon({ icon, className }: { icon: string | null | undefined; className?: string }) {
  const Icon = (icon && PROVIDER_ICONS[icon]) || Plug;
  return (
    <span
      className={cn(
        'flex size-10 shrink-0 items-center justify-center rounded-(--fx-r-m) bg-(--fx-link-bg) text-(--fx-link)',
        className,
      )}
    >
      <Icon aria-hidden="true" className="size-5" />
    </span>
  );
}

/** The last test's result, next to the action that ran it. */
export function FxTestResultLine({ result, className }: { result: ConnectionTestState | undefined; className?: string }) {
  const { formatTime } = useDatetime();
  if (!result) return null;
  if (result === 'testing') {
    return (
      <p role="status" className={cn('flex items-center gap-1.5 text-sm text-(--fx-ink-2)', className)}>
        <Loader2 aria-hidden="true" className="size-3.5 animate-spin" />
        Testing the connection
      </p>
    );
  }
  return (
    <p
      role={result.ok ? 'status' : 'alert'}
      data-fx-test-result={result.ok ? 'ok' : 'failed'}
      className={cn(
        'text-sm [overflow-wrap:anywhere]',
        result.ok
          ? 'text-(--fx-ok-ink)'
          : 'font-semibold text-[color-mix(in_srgb,var(--fx-act)_82%,var(--fx-surface))]',
        className,
      )}
    >
      {result.ok ? `${result.message} Checked ${formatTime(result.checkedAt)}.` : result.message}
    </p>
  );
}
