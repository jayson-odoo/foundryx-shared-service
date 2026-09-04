'use client';

import { Fragment } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { PageHeader } from '@/components/platform/page-header';
import { MeetingsSettingsView } from './meetings-settings-view';

export default function MeetingsSettingsPage() {
  return (
    <RequirePermission permission="meetings.settings.manage">
      <Fragment>
        <PageHeader title="Meetings settings" />
        <Container width="fluid">
          <MeetingsSettingsView />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
