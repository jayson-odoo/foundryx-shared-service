'use client';

import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { PageHeader } from '@/components/platform/page-header';
import { MyMeetingsView } from './my-meetings-view';

export default function MyMeetingsPage() {
  return (
    <RequirePermission permission="meetings.view">
      <Container width="fluid">
        <PageHeader />
        <MyMeetingsView />
      </Container>
    </RequirePermission>
  );
}
