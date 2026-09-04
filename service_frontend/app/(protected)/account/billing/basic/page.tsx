'use client';

import { Fragment } from 'react';
import { useSettings } from '@/providers/settings-provider';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { AccountBasicContent } from '@/app/(protected)/account/billing/basic/content';
import { PageNavbar } from '@/app/(protected)/account/page-navbar';

export default function AccountBasicPage() {
  const { settings } = useSettings();

  return (
    <Fragment>
      <PageNavbar />
      {settings?.layout === 'demo1' && (
        <Container>
          <PageHeader
            description="Central Hub for Personal Customization"
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline">Order History</Button>
              </div>
            }
          />
        </Container>
      )}
      <Container>
        <AccountBasicContent />
      </Container>
    </Fragment>
  );
}
