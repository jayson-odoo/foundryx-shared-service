'use client';

import Link from 'next/link';
import { LoaderCircleIcon, Pencil } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardHeading, CardTitle, CardToolbar } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { FormRow } from '@/components/platform/resource-form';
import { ClampedText } from '@/components/platform/clamped-text';
import { useCan } from '@/hooks/use-can';
import { useDatetime } from '@/hooks/use-datetime';
import type { ConnectorSettingsAuditItem, ConnectorTenantField } from '@/types/connector';
import { TENANT_FIELDS, TENANT_INT_FIELDS } from './connector-settings-schema';
import { SourceBadge } from './source-badge';
import { useConnectorAccess } from './use-connector-access';
import { useConnectorProducts } from './use-connector-products';
import { productPath } from './use-connector-product-form';

export const TENANT_LABELS: Record<ConnectorTenantField, string> = {
  publicBaseUrl: 'Public base URL',
  allowedClientCidrs: 'Allowed client IP ranges',
  redirectAllowlist: 'Allowed redirect URLs',
  manifestTtlSeconds: 'Manifest cache (seconds)',
  callTimeoutSeconds: 'Call timeout (seconds)',
  callLogRetentionDays: 'Call log retention (days)',
};

const FIELD_LABELS: Record<string, string> = {
  ...TENANT_LABELS,
  displayName: 'Display name',
  connectionId: 'Connection ID',
  consentUrl: 'Consent URL',
  apiBaseUrl: 'API base URL',
  issuer: 'Issuer',
  consentAudience: 'Consent audience',
  callAudience: 'Call audience',
  ssToProductSecret: 'Secret to product',
  productToSsSecret: 'Secret from product',
};

function auditTarget(item: ConnectorSettingsAuditItem): string {
  return item.target === 'tenant' ? 'Access' : item.target.replace(/^product:/, 'Product ');
}

function AuditCard({ audit }: { audit: ConnectorSettingsAuditItem[] }) {
  const { formatDateTime } = useDatetime();
  return (
    <Card>
      <CardHeader>
        <CardHeading>
          <CardTitle>Recent changes</CardTitle>
        </CardHeading>
      </CardHeader>
      <CardContent>
        {audit.length === 0 ? (
          <p className="text-sm text-muted-foreground">No changes yet.</p>
        ) : (
          <ul className="flex flex-col divide-y divide-border">
            {audit.map((a) => (
              <li key={a.id} className="grid grid-cols-1 gap-1 py-2.5 text-sm md:grid-cols-[180px_160px_1fr] md:gap-4">
                <span className="text-muted-foreground">{formatDateTime(a.at)}</span>
                <span>{a.actorName ?? 'Unknown user'}</span>
                <ClampedText
                  text={`${auditTarget(a)} ${a.action}${
                    a.fields.length ? `: ${a.fields.map((f) => FIELD_LABELS[f] ?? f).join(', ')}` : ''
                  }`}
                />
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/** The products these settings apply to, linked to their own settings pages. */
function ProductsCard() {
  const { products, isLoading } = useConnectorProducts();
  return (
    <Card>
      <CardHeader>
        <CardHeading>
          <CardTitle>Products</CardTitle>
        </CardHeading>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <LoaderCircleIcon className="size-4 animate-spin text-muted-foreground" />
        ) : products.length === 0 ? (
          <p className="text-sm text-muted-foreground">No products yet.</p>
        ) : (
          <ul className="flex flex-wrap gap-2" data-testid="access-products">
            {products.map((p) => (
              <li key={p.key}>
                <Button variant="outline" size="sm" asChild>
                  <Link href={productPath(p.key)}>{p.displayName ?? p.key}</Link>
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/** Tenant-level connector settings (database > environment > default). */
export function AccessTab() {
  const { can } = useCan();
  const canEdit = can('connector.settings');
  const a = useConnectorAccess();

  if (a.isLoading && !a.settings) {
    return (
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <LoaderCircleIcon className="size-6 animate-spin" />
      </div>
    );
  }

  if (!a.settings) {
    return (
      <div className="flex flex-col items-center gap-3 py-24 text-center">
        <p className="text-sm font-medium">Could not load connector settings.</p>
        <Button variant="outline" size="sm" onClick={() => void a.reload()}>
          Retry
        </Button>
      </div>
    );
  }

  const s = a.settings;
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardHeading>
            <CardTitle>Access</CardTitle>
          </CardHeading>
          {canEdit && (
            <CardToolbar>
              {a.editing ? (
                <>
                  <Button variant="outline" size="sm" disabled={a.saving} onClick={a.cancel}>
                    Cancel
                  </Button>
                  <Button size="sm" disabled={a.saving} onClick={() => void a.save()}>
                    {a.saving && <LoaderCircleIcon className="animate-spin" />}
                    Save settings
                  </Button>
                </>
              ) : (
                <Button variant="outline" size="sm" onClick={a.startEdit}>
                  <Pencil />
                  Edit
                </Button>
              )}
            </CardToolbar>
          )}
        </CardHeader>
        <CardContent className="flex flex-col">
          {TENANT_FIELDS.map((f) => {
            const v = s[f];
            const limit = s.ceilings?.[f];
            const limitLine = limit ? (
              <span className="break-all text-xs text-muted-foreground" data-testid={`limit-${f}`}>
                {`Deployment limit: ${limit}`}
              </span>
            ) : null;
            if (a.editing && a.values) {
              return (
                <FormRow key={f} label={TENANT_LABELS[f]}>
                  <div className="flex max-w-xl flex-col gap-2">
                    <Input
                      aria-label={TENANT_LABELS[f]}
                      inputMode={TENANT_INT_FIELDS.includes(f) ? 'numeric' : undefined}
                      value={a.values[f]}
                      placeholder={v.source !== 'database' ? (v.value ?? undefined) : undefined}
                      aria-invalid={!!a.errors[f]}
                      onChange={(e) => a.setValue(f, e.target.value)}
                    />
                    {limitLine}
                    {a.errors[f] && <p className="text-sm text-destructive">{a.errors[f]}</p>}
                  </div>
                </FormRow>
              );
            }
            return (
              <FormRow key={f} label={TENANT_LABELS[f]}>
                <div className="flex min-w-0 flex-col gap-2">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="min-w-0 break-all font-mono text-xs">{v.value || '-'}</span>
                    <SourceBadge source={v.source} />
                  </div>
                  {limitLine}
                </div>
              </FormRow>
            );
          })}
        </CardContent>
      </Card>
      <ProductsCard />
      <AuditCard audit={a.audit} />
    </div>
  );
}
