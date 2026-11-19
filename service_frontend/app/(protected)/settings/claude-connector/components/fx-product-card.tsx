'use client';

/**
 * A connector product as a connected service, with the Foundryx UIUX switch
 * on (gap audit 12 "Connected services", 11 "Secrets shown once"): its name,
 * its state as a status chip, the reason in plain words when it needs
 * attention, its facts, and whether each secret is saved (never the secret,
 * which the API does not return here). The same links and the same manifest
 * refresh as today's card.
 */
import Link from 'next/link';
import { Check, Copy, LoaderCircleIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { FxIconActionButton } from '@/components/fx/actions/icon-action';
import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard';
import { useDatetime } from '@/hooks/use-datetime';
import type { ConnectorProduct, ConnectorSecretState } from '@/types/connector';
import { productPath } from './use-connector-product-form';

export type FxChipTone = 'ok' | 'warn' | 'neutral';

const CHIP: Record<FxChipTone, string> = {
  ok: 'bg-(--fx-ok-bg) text-(--fx-ok-ink)',
  warn: 'bg-(--fx-warn-bg) text-(--fx-warn-ink)',
  neutral: 'bg-(--fx-chip) text-(--fx-chip-ink)',
};

/** The playbook's status chip. */
export function FxChip({ tone, children }: { tone: FxChipTone; children: string }) {
  return (
    <span
      className={cn(
        'inline-flex h-6 shrink-0 items-center rounded-(--fx-r-pill) px-2.5 text-xs font-semibold',
        CHIP[tone],
      )}
    >
      {children}
    </span>
  );
}

/** A secret's state: saved or not, never its value. */
export function FxSecretStateChip({ state }: { state: ConnectorSecretState }) {
  return <FxChip tone={state === 'set' ? 'ok' : 'warn'}>{state === 'set' ? 'Saved' : 'Not set'}</FxChip>;
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-0.5 md:grid-cols-[180px_1fr] md:items-center md:gap-4">
      <dt className="text-sm text-(--fx-ink-3)">{label}</dt>
      <dd className="min-w-0 text-sm text-(--fx-ink)">{children}</dd>
    </div>
  );
}

export interface FxProductCardProps {
  product: ConnectorProduct;
  canManage: boolean;
  canEdit: boolean;
  refreshing: boolean;
  onRefresh: () => void;
}

export function FxProductCard({ product, canManage, canEdit, refreshing, onRefresh }: FxProductCardProps) {
  const { formatDateTime, formatRelative } = useDatetime();
  const { isCopied, copyToClipboard } = useCopyToClipboard({ timeout: 1400 });
  const name = product.displayName ?? product.key;
  const misconfigured = product.status === 'misconfigured';
  const needsAttention = misconfigured || product.stale;
  const editLabel = canEdit ? `Edit ${name} settings` : `${name} settings`;

  return (
    <section
      aria-label={name}
      data-fx-product-card={product.key}
      className="flex flex-col gap-4 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-4 md:p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1.5">
          <h2 className="font-semibold leading-tight text-(--fx-ink) [overflow-wrap:anywhere]">{name}</h2>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <FxChip tone={needsAttention ? 'warn' : 'ok'}>{needsAttention ? 'Needs attention' : 'Ready'}</FxChip>
            {product.fetchedAt && (
              <span className="text-sm text-(--fx-ink-3)" title={formatDateTime(product.fetchedAt)}>
                Manifest fetched {formatRelative(product.fetchedAt)}
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {canManage && !misconfigured && (
            <FxIconActionButton
              label={refreshing ? 'Refreshing manifest' : 'Refresh manifest'}
              icon="refresh"
              iconNode={refreshing ? <LoaderCircleIcon aria-hidden="true" className="size-[18px] animate-spin" /> : undefined}
              disabledReason={refreshing ? 'Refreshing now.' : undefined}
              onClick={onRefresh}
            />
          )}
          <Button variant="fx-quiet" className="h-auto min-h-11 px-4" asChild>
            <Link href={productPath(product.key)} aria-label={editLabel}>
              {canEdit ? 'Edit' : 'Settings'}
            </Link>
          </Button>
        </div>
      </div>

      {misconfigured && (
        <p className="text-sm text-(--fx-warn-ink)">Required settings are missing, so Claude cannot use {name}.</p>
      )}
      {product.stale && (
        <p className="text-sm text-(--fx-warn-ink)">
          {`The last manifest refresh failed (${product.lastError ?? 'unknown'}). Serving the copy fetched ${
            product.fetchedAt ? formatDateTime(product.fetchedAt) : 'earlier'
          }.`}
        </p>
      )}

      <dl className="flex flex-col gap-2.5">
        <Fact label="MCP URL">
          <div className="flex items-center gap-2">
            <span className="min-w-0 font-mono text-xs [overflow-wrap:anywhere]">{product.mcpUrl}</span>
            <Button
              type="button"
              variant="fx-icon"
              className="h-auto min-h-9 min-w-9 shrink-0 rounded-(--fx-r-pill) px-2"
              aria-label={isCopied ? 'Copied' : 'Copy MCP URL'}
              onClick={() => copyToClipboard(product.mcpUrl)}
            >
              {isCopied ? <Check aria-hidden="true" className="size-4 text-(--fx-ok)" /> : <Copy aria-hidden="true" className="size-4" />}
            </Button>
          </div>
        </Fact>
        <Fact label="Consent URL">
          <span className="font-mono text-xs [overflow-wrap:anywhere]">{product.consentUrl}</span>
        </Fact>
        <Fact label="API base">
          <span className="font-mono text-xs [overflow-wrap:anywhere]">{product.apiBase}</span>
        </Fact>
        <Fact label="Manifest version">{product.manifestVersion}</Fact>
        <Fact label="Tools">{product.toolCount}</Fact>
        <Fact label="Secret to product">
          <FxSecretStateChip state={product.secrets.ssToProduct} />
        </Fact>
        <Fact label="Secret from product">
          <FxSecretStateChip state={product.secrets.productToSs} />
        </Fact>
      </dl>
    </section>
  );
}
