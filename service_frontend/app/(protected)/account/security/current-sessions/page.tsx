'use client';

import { Fragment } from 'react';
import Link from 'next/link';
import { useSettings } from '@/providers/settings-provider';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { PageNavbar } from '@/app/(protected)/account/page-navbar';
import { AccountCurrentSessionsContent } from '@/app/(protected)/account/security/current-sessions/content';

export default function AccountCurrentSessionsPage() {
  const { settings } = useSettings();

  return (
    <Fragment>
      <PageNavbar />
      {settings?.layout === 'demo1' && (
        <Container>
          <PageHeader
            description="Authorized Devices for Report Access"
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline">
                  <Link href="/account/security/security-log">
                    Activity Log
                  </Link>
                </Button>
              </div>
            }
          />
        </Container>
      )}
      <Container>
        <AccountCurrentSessionsContent />
      </Container>
    </Fragment>
  );
}
