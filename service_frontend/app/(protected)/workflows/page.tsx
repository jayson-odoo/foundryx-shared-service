'use client';

import { Fragment } from 'react';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { RequirePermission } from '@/components/common/require-permission';
import { useWorkflowsListConfig } from './components/use-workflows-list-config';

export default function WorkflowsPage() {
  const config = useWorkflowsListConfig();

  return (
    <RequirePermission permission="workflows.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>
                Automate work — triggers run actions like sending emails, on a schedule or on demand.
              </ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
