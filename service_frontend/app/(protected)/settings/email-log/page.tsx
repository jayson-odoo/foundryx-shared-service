'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useEmailLogListConfig } from './components/use-email-log-list-config';

export default function EmailLogPage() {
  const config = useEmailLogListConfig();

  return (
    <RequirePermission permission="emails.read">
      <Fragment>
        <Container width="fluid">
          <ResourceList config={config} />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
