'use client';

import { Fragment } from 'react';
import Link from 'next/link';
import { useSettings } from '@/providers/settings-provider';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { AccountNotificationsContent } from '@/app/(protected)/account/notifications/content';
import { PageNavbar } from '@/app/(protected)/account/page-navbar';

export default function AccountNotificationsPage() {
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
                <Button variant="outline">
                  <Link href="#">Privacy Settings</Link>
                </Button>
              </div>
            }
          />
        </Container>
      )}
      <Container>
        <AccountNotificationsContent />
      </Container>
    </Fragment>
  );
}
