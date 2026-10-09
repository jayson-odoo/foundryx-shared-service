'use client';

import { Check, Copy, LoaderCircleIcon, RefreshCw, TriangleAlert } from 'lucide-react';
import { Alert, AlertContent, AlertDescription, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useCan } from '@/hooks/use-can';
import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard';
import { useDatetime } from '@/hooks/use-datetime';
import type { ConnectorProduct, ConnectorSecretState } from '@/types/connector';
import { useConnectorProducts } from './use-connector-products';

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1 md:grid-cols-[200px_1fr] md:items-center md:gap-4">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-sm">{children}</dd>
    </div>
  );
}

function SecretBadge({ state }: { state: ConnectorSecretState }) {
  return (
    <Badge variant={state === 'set' ? 'success' : 'destructive'} appearance="light" size="sm">
      {state === 'set' ? 'Set' : 'Missing'}
    </Badge>
  );
}

function ProductCard({
  product,
  canManage,
  refreshing,
  onRefresh,
}: {
  product: ConnectorProduct;
  canManage: boolean;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const { formatDateTime } = useDatetime();
  const { isCopied, copyToClipboard } = useCopyToClipboard();

  return (
    <Card>
      <CardHeader>
        <CardTitle>{product.displayName ?? product.key}</CardTitle>
        {canManage && (
          <Button type="button" size="sm" variant="outline" disabled={refreshing} onClick={onRefresh}>
            {refreshing ? <LoaderCircleIcon className="animate-spin" /> : <RefreshCw />}
            Refresh manifest
          </Button>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {product.stale && (
          <Alert variant="warning" appearance="light">
            <AlertIcon>
              <TriangleAlert />
            </AlertIcon>
            <AlertContent>
              <AlertTitle>Manifest is stale</AlertTitle>
              <AlertDescription>
                {product.lastError && <span className="block">{product.lastError}</span>}
                {product.fetchedAt && (
                  <span className="block">Last good fetch {formatDateTime(product.fetchedAt)}</span>
                )}
              </AlertDescription>
            </AlertContent>
          </Alert>
        )}
        <dl className="flex flex-col gap-3">
          <Fact label="MCP URL">
            <div className="flex items-center gap-2">
              <span className="min-w-0 break-all font-mono text-xs">{product.mcpUrl}</span>
              <Button
                type="button"
                variant="outline"
                mode="icon"
                size="sm"
                aria-label="Copy MCP URL"
                onClick={() => copyToClipboard(product.mcpUrl)}
              >
                {isCopied ? <Check className="text-green-600" /> : <Copy />}
              </Button>
            </div>
          </Fact>
          <Fact label="Consent URL">
            <span className="break-all font-mono text-xs">{product.consentUrl}</span>
          </Fact>
          <Fact label="API base">
            <span className="break-all font-mono text-xs">{product.apiBase}</span>
          </Fact>
          <Fact label="Manifest version">
            <span>{product.manifestVersion}</span>
          </Fact>
          <Fact label="Tools">
            <span>{product.toolCount}</span>
          </Fact>
          {!product.stale && product.fetchedAt && (
            <Fact label="Fetched">
              <span>{formatDateTime(product.fetchedAt)}</span>
            </Fact>
          )}
          <Fact label="Secret to product">
            <SecretBadge state={product.secrets.ssToProduct} />
          </Fact>
          <Fact label="Secret from product">
            <SecretBadge state={product.secrets.productToSs} />
          </Fact>
        </dl>
      </CardContent>
    </Card>
  );
}

/** Read-only Products tab (AC-19-61): facts, secret set/missing, manifest refresh. */
export function ProductsTab() {
  const { can } = useCan();
  const { products, isLoading, refreshingKey, refresh } = useConnectorProducts();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <LoaderCircleIcon className="size-6 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {products.map((p) => (
        <ProductCard
          key={p.key}
          product={p}
          canManage={can('connector.manage')}
          refreshing={refreshingKey === p.key}
          onRefresh={() => void refresh(p.key)}
        />
      ))}
    </div>
  );
}
