'use client';

import { Fragment } from 'react';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { IdeasView } from './ideas-view';

/**
 * Idea repository (plan Phase A) - the operator page. Renders the shared
 * {@link IdeasView} grid in operator mode (app JWT + `/ideation/*` routes; the
 * ideation runtime default). The same grid renders chrome-less in the host
 * iframe via the embed runtime (WS-C1).
 */
export default function IdeasPage() {
  return (
    <Fragment>
      <Container width="fluid">
        <Toolbar>
          <ToolbarHeading>
            <ToolbarPageTitle />
            <ToolbarDescription>
              The raw idea repository - drag the grip to reprioritise (top = highest).
            </ToolbarDescription>
          </ToolbarHeading>
        </Toolbar>
      </Container>
      <Container width="fluid">
        <IdeasView />
      </Container>
    </Fragment>
  );
}
