'use client';

/**
 * Small parts the log pages share under the Foundryx UIUX switch (slice
 * W3-LOGS): developer logs, the email log, AI traces and AutoCount calls.
 * Only ever rendered with the switch on; every page keeps its own markup
 * with the switch off.
 *
 * Logs can hold personal data and secrets, so Hold to Copy is only put on
 * identifiers and moments, never on a body, a payload, a header value, an
 * error text or a prompt.
 */
import type { ReactNode } from 'react';
import { useSession } from 'next-auth/react';
import { useDatetime } from '@/hooks/use-datetime';
import { FxHoldToCopy } from '@/components/fx/copy/hold-to-copy';
import { FxMoment } from '@/components/fx/fields/fx-moment';
import { FormRow } from '@/components/platform/resource-form/form-row';

/**
 * A moment in a list: relative ("5 min", "Yesterday") with the full
 * "14 Nov 2026, 2:14 pm" as its tooltip; holding it copies the full form.
 */
export function FxListMoment({ iso, className }: { iso: string | null | undefined; className?: string }) {
  const { formatDateTime } = useDatetime();
  if (!iso) return <span className={className}>-</span>;
  return (
    <FxHoldToCopy text={formatDateTime(iso)}>
      <FxMoment iso={iso} className={className} />
    </FxHoldToCopy>
  );
}

/**
 * One label and value on a read-only detail: the value as plain text.
 * `copy` makes it Hold to Copy (identifiers and moments only); a string
 * `copy` is what gets copied when the visible text is not.
 */
export function FxDetailRow({
  label,
  copy,
  children,
}: {
  label: string;
  copy?: boolean | string;
  children: ReactNode;
}) {
  // FormRow under the switch makes a bare string copyable by itself, so a
  // value that must not copy is always passed inside an element.
  const value = copy ? (
    <FxHoldToCopy text={typeof copy === 'string' ? copy : undefined}>
      <span className="break-all">{children}</span>
    </FxHoldToCopy>
  ) : (
    <span className="break-words">{children}</span>
  );
  return <FormRow label={label}>{value}</FormRow>;
}

/** Who did it, for "by Kay" on done toasts. */
export function useFxByWhom(): string | undefined {
  return useSession().data?.user?.name ?? undefined;
}
