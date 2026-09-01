'use client';

import { Fragment } from 'react';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { MediaCapsForm } from './media-caps-form';

/**
 * Omnichannel media limits (plan 12 Slice 3, AC-12-23) - per-type max upload
 * sizes for WhatsApp media. Gated by channels.manage. v1 edits the tenant
 * default scope. BL: an optional per-workspace scope selector is a follow-up.
 */
export default function MediaLimitsPage() {
  return (
    <RequirePermission permission="channels.manage">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>
                Maximum upload sizes and accepted file types for WhatsApp media.
              </ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <MediaCapsForm />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
