'use client';

import { Fragment } from 'react';
import Link from 'next/link';
import { useSettings } from '@/providers/settings-provider';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { AccountPermissionsCheckContent } from '@/app/(protected)/account/members/permissions-check/content';
import { PageNavbar } from '@/app/(protected)/account/page-navbar';

export default function AccountPermissionsCheckPage() {
  const { settings } = useSettings();

  return (
    <Fragment>
      <PageNavbar />
      {settings?.layout === 'demo1' && (
        <Container>
          <PageHeader
            description="Overview of all team members and roles."
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline">
                  <Link href="#">View Roles</Link>
                </Button>
              </div>
            }
          />
        </Container>
      )}
      <Container>
        <AccountPermissionsCheckContent />
      </Container>
    </Fragment>
  );
}
