'use client';

import { Fragment } from 'react';
import Link from 'next/link';
import { useSettings } from '@/providers/settings-provider';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { PageNavbar } from '@/app/(protected)/account/page-navbar';
import { AccountAllowedIPAddressesContent } from '@/app/(protected)/account/security/allowed-ip-addresses/content';

export default function AccountAllowedIPAddressesPage() {
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
                  <Link href="#">Security Overview</Link>
                </Button>
              </div>
            }
          />
        </Container>
      )}
      <Container>
        <AccountAllowedIPAddressesContent />
      </Container>
    </Fragment>
  );
}
