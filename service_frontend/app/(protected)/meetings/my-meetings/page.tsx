'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { PageHeader } from '@/components/platform/page-header';
import { MyMeetingsView } from './my-meetings-view';

export default function MyMeetingsPage() {
  return (
    <RequirePermission permission="meetings.view">
      <Fragment>
        <PageHeader />
        <Container width="fluid">
          <MyMeetingsView />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
