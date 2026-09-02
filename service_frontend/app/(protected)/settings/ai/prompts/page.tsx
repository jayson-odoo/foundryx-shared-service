'use client';

import { Fragment } from 'react';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { RequirePlatformPermission } from '@/components/common/require-platform-permission';
import { PromptsListView } from './prompts-list-view';

const PROMPTS_PERMISSION = 'ai_prompts.manage';

export default function AiPromptsPage() {
  return (
    <RequirePlatformPermission permission={PROMPTS_PERMISSION}>
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle text="AI prompts" />
              <ToolbarDescription>
                Every version is kept - publishing moves the production label, nothing is
                overwritten.
              </ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <PromptsListView />
        </Container>
      </Fragment>
    </RequirePlatformPermission>
  );
}
