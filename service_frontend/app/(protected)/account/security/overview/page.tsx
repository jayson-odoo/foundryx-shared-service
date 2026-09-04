'use client';

import { Fragment } from 'react';
import Link from 'next/link';
import { useSettings } from '@/providers/settings-provider';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { PageNavbar } from '@/app/(protected)/account/page-navbar';
import { AccountOverviewContent } from '@/app/(protected)/account/security/overview/content';

export default function AccountOverviewPage() {
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
                  <Link href="/account/security/overview">
                    Security History
                  </Link>
                </Button>
              </div>
            }
          />
        </Container>
      )}
      <Container>
        <AccountOverviewContent />
      </Container>
    </Fragment>
  );
}
