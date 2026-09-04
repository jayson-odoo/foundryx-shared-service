'use client';

import { Fragment } from 'react';
import Link from 'next/link';
import { useSettings } from '@/providers/settings-provider';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { AccountTeamMembersContent } from '@/app/(protected)/account/members/team-members/content';
import { PageNavbar } from '@/app/(protected)/account/page-navbar';

export default function AccountTeamMembersPage() {
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
                  <Link href="#">Import Members</Link>
                </Button>
                <Button>
                  <Link href="#">Add Member</Link>
                </Button>
              </div>
            }
          />
        </Container>
      )}
      <Container>
        <AccountTeamMembersContent />
      </Container>
    </Fragment>
  );
}
