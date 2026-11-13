'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useTemplatesListConfig } from './components/use-templates-list-config';

export default function TemplatesPage() {
  const config = useTemplatesListConfig();

  return (
    <RequirePermission permission="templates.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
