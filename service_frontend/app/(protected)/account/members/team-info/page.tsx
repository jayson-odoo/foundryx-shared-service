'use client';

import { Fragment } from 'react';
import Link from 'next/link';
import { useSettings } from '@/providers/settings-provider';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { AccountTeamInfoContent } from '@/app/(protected)/account/members/team-info/content';
import { PageNavbar } from '@/app/(protected)/account/page-navbar';

export default function AccountTeamInfoPage() {
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
                  <Link href="#">Roles</Link>
                </Button>
              </div>
            }
          />
        </Container>
      )}
      <Container>
        <AccountTeamInfoContent />
      </Container>
    </Fragment>
  );
}
