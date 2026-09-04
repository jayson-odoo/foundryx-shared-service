'use client';

import { Fragment } from 'react';
import Link from 'next/link';
import { useSettings } from '@/providers/settings-provider';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { AccountTeamsStarterContent } from '@/app/(protected)/account/members/team-starter/content';
import { PageNavbar } from '@/app/(protected)/account/page-navbar';

export default function AccountTeamsStarterPage() {
  const { settings } = useSettings();

  return (
    <Fragment>
      <PageNavbar />
      {settings?.layout === 'demo1' && (
        <Container>
          <PageHeader
            description="Efficient team organization with real-time updates"
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline">
                  <Link href="#">Plans</Link>
                </Button>
              </div>
            }
          />
        </Container>
      )}
      <Container>
        <AccountTeamsStarterContent />
      </Container>
    </Fragment>
  );
}
