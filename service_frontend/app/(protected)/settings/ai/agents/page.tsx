'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useAgentsListConfig } from '../components/use-agents-list-config';

export default function AiAgentsPage() {
  const config = useAgentsListConfig();

  return (
    <RequirePermission permission="ai_agents.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
