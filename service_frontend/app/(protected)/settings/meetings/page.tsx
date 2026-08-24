'use client';

import { Fragment } from 'react';
import { Toolbar, ToolbarHeading, ToolbarPageTitle } from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { MeetingsSettingsView } from './meetings-settings-view';

export default function MeetingsSettingsPage() {
  return (
    <RequirePermission permission="meetings.settings.manage">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <MeetingsSettingsView />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
