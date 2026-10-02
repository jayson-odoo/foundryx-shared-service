'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useTracesListConfig } from '../components/use-traces-list-config';

export default function AiTracesPage() {
  const config = useTracesListConfig();

  return (
    <RequirePermission permission="ai_traces.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
