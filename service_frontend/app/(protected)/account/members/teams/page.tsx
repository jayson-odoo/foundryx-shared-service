'use client';

import { Fragment } from 'react';
import Link from 'next/link';
import { useSettings } from '@/providers/settings-provider';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { AccountTeamsContent } from '@/app/(protected)/account/members/teams/content';
import { PageNavbar } from '@/app/(protected)/account/page-navbar';

export default function AccountTeamsPage() {
  const { settings } = useSettings();

  return (
    <Fragment>
      <PageNavbar />
      {settings?.layout === 'demo1' && (
        <Container>
          <PageHeader
            description="efficient team organization with real-time updates"
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline">
                  <Link href="#">Add New Team</Link>
                </Button>
              </div>
            }
          />
        </Container>
      )}
      <Container>
        <AccountTeamsContent />
      </Container>
    </Fragment>
  );
}
