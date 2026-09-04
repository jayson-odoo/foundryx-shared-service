'use client';

import { Fragment } from 'react';
import Link from 'next/link';
import { useSettings } from '@/providers/settings-provider';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { PageNavbar } from '@/app/(protected)/account/page-navbar';
import { AccountSecurityLogContent } from '@/app/(protected)/account/security/security-log/content';

export default function AccountSecurityLogPage() {
  const { settings } = useSettings();

  return (
    <Fragment>
      <PageNavbar />
      {settings?.layout === 'demo1' && (
        <Container>
          <PageHeader
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline">
                  <Link href="#">Security Overview</Link>
                </Button>
              </div>
            }
          />
        </Container>
      )}
      <Container>
        <AccountSecurityLogContent />
      </Container>
    </Fragment>
  );
}
