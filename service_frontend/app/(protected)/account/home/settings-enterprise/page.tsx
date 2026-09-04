'use client';

import { Fragment } from 'react';
import Link from 'next/link';
import { useSettings } from '@/providers/settings-provider';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { AccountSettingsEnterpriseContent } from '@/app/(protected)/account/home/settings-enterprise/content';
import { PageNavbar } from '@/app/(protected)/account/page-navbar';

export default function AccountSettingsEnterprisePage() {
  const { settings } = useSettings();

  return (
    <Fragment>
      <PageNavbar />
      {settings?.layout === 'demo1' && (
        <Container>
          <PageHeader
            description="Tailored Tools for Business Scalability"
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline">
                  <Link href="#">Public Profile</Link>
                </Button>
                <Button>
                  <Link href="#">My profile</Link>
                </Button>
              </div>
            }
          />
        </Container>
      )}
      <Container>
        <AccountSettingsEnterpriseContent />
      </Container>
    </Fragment>
  );
}
