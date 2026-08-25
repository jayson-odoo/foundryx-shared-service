'use client';

import { Fragment, useCallback, useEffect, useState } from 'react';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { RequirePermission } from '@/components/common/require-permission';
import { ideationService } from '@/services/ideation-service';
import type { Product } from '@/types/ideation';
import type { EmbedConnectionItem } from '@/types/embed-connection';
import { useEmbedConnectionsListConfig } from './use-embed-connections-list-config';
import { EmbedConnectionCreateDialog } from './embed-connection-create-dialog';
import { RotateSecretDialog } from './rotate-secret-dialog';

/**
 * Embed connections admin (PLAN-ideation-embed-sso §7, AC-E-5/12) on the shared
 * ResourceList. Registers the host apps allowed to embed this tenant's Ideas
 * workspace - the UI replacement for the `seed_ideation_embed_connection.py`
 * docker script. Add opens the create modal (secret revealed once); each row
 * exposes Rotate secret, Activate/Deactivate, and hard Delete. Products load once
 * to resolve the product-scope column to names + feed the create picker.
 */
function EmbedConnectionsView() {
  const [products, setProducts] = useState<Product[]>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [rotating, setRotating] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    ideationService
      .listProducts()
      .then(setProducts)
      .catch(() => setProducts([]));
  }, []);

  const bump = useCallback(() => setVersion((v) => v + 1), []);

  const { config } = useEmbedConnectionsListConfig(products, {
    onCreate: () => setCreateOpen(true),
    onRotate: (item: EmbedConnectionItem) => setRotating(item.connectionId),
  });

  return (
    <Fragment>
      <ResourceList key={version} config={config} />
      <EmbedConnectionCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        products={products}
        onCreated={bump}
      />
      <RotateSecretDialog
        connectionId={rotating}
        onOpenChange={(open) => !open && setRotating(null)}
        onRotated={bump}
      />
    </Fragment>
  );
}

export default function EmbedConnectionsPage() {
  return (
    <RequirePermission permission="ideation.triage.manage">
      <Container width="fluid">
        <Toolbar>
          <ToolbarHeading>
            <ToolbarPageTitle />
            <ToolbarDescription>
              Host apps allowed to embed this tenant&apos;s Ideas workspace. The signing secret is
              shown once on create or rotate - paste the same value into the host&apos;s embed config.
            </ToolbarDescription>
          </ToolbarHeading>
        </Toolbar>
      </Container>
      <Container width="fluid">
        <EmbedConnectionsView />
      </Container>
    </RequirePermission>
  );
}
