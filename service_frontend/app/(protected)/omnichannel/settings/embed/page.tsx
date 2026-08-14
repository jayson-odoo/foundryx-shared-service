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

/**
 * Embed access (plan 11H) - a tenant admin provisions + manages the embed
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
                Embed the conversation UI as a token-authed iframe on your own pages.
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
