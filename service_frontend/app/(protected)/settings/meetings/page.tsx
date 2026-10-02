'use client';

import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { PageHeader } from '@/components/platform/page-header';
import { MeetingsSettingsView } from './meetings-settings-view';

export default function MeetingsSettingsPage() {
  return (
    <RequirePermission permission="meetings.settings.manage">
      <Container width="fluid">
        <PageHeader title="Meetings settings" />
        <MeetingsSettingsView />
      </Container>
    </RequirePermission>
  );
}
