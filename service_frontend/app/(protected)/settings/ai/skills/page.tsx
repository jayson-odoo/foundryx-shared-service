'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useSkillsListConfig } from '../components/use-skills-list-config';

export default function AiSkillsPage() {
  const config = useSkillsListConfig();

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
