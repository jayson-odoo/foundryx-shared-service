'use client';

import { Fragment } from 'react';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { EmbedAccessPanel } from './embed-access-panel';

// The consumer mints assertions on their own backend — the integration guide §12
// covers those steps. Shipped as a doc artifact; operators serve it in prod.
const INTEGRATION_GUIDE_URL = '/documentation/omnichannel/consumer-integration-guide.md';

/**
 * Embed access (plan 11H) — a tenant admin provisions + manages the embed
 * connection (connection id, write-only signing secret, allowed origins) and
 * copies the iframe snippet. Gated by workspaces.manage.
 */
export default function EmbedAccessPage() {
  return (
    <RequirePermission permission="workspaces.manage">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>
                Embed the conversation UI as a token-authed iframe on your own pages.{' '}
                <a
                  href={INTEGRATION_GUIDE_URL}
                  target="_blank"
                  rel="noreferrer"
                  className="text-primary hover:underline"
                >
                  Integration guide (§12)
                </a>
              </ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <EmbedAccessPanel />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
