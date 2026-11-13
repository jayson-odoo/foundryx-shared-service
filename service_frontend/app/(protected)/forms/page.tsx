'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useFormsListConfig } from './components/use-forms-list-config';

export default function FormsPage() {
  const config = useFormsListConfig();

  return (
    <RequirePermission permission="forms.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
