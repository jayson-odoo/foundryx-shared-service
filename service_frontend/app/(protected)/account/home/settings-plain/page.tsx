'use client';

import { Fragment } from 'react';
import Link from 'next/link';
import { useSettings } from '@/providers/settings-provider';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { AccountSettingsPlainContent } from '@/app/(protected)/account/home/settings-plain/content';
import { PageNavbar } from '@/app/(protected)/account/page-navbar';

export default function AccountSettingsPlainPage() {
  const { settings } = useSettings();

  return (
    <Fragment>
      <PageNavbar />
      {settings?.layout === 'demo1' && (
        <Container>
          <PageHeader
            description="Clean, Efficient User Experience"
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline">
                  <Link href="#">Public Profile</Link>
                </Button>
                <Button>
                  <Link href="#">Get Started</Link>
                </Button>
              </div>
            }
          />
        </Container>
      )}
      <Container>
        <AccountSettingsPlainContent />
      </Container>
    </Fragment>
  );
}
