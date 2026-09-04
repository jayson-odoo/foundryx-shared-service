'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { PageHeader } from '@/components/platform/page-header';
import { EmbedAccessPanel } from './embed-access-panel';

/**
 * Embed access (plan 11H) - a tenant admin provisions + manages the embed
 * connection (connection id, write-only signing secret, allowed origins) and
 * copies the iframe snippet. Gated by workspaces.manage.
 */
export default function EmbedAccessPage() {
  return (
    <RequirePermission permission="workspaces.manage">
      <Fragment>
        <PageHeader description="Embed the conversation UI as a token-authed iframe on your own pages." />
        <Container width="fluid">
          <EmbedAccessPanel />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
