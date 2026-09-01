'use client';

import { Fragment } from 'react';
import { Toolbar, ToolbarHeading, ToolbarPageTitle } from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { MyMeetingsView } from './my-meetings-view';

export default function MyMeetingsPage() {
  return (
    <RequirePermission permission="meetings.view">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <MyMeetingsView />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
