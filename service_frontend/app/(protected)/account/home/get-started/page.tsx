'use client';

import { Fragment } from 'react';
import Link from 'next/link';
import { useSettings } from '@/providers/settings-provider';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { AccountGetStartedContent } from '@/app/(protected)/account/home/get-started/content';
import { PageNavbar } from '@/app/(protected)/account/page-navbar';

export default function AccountGetStartedPage() {
  const { settings } = useSettings();

  return (
    <Fragment>
      <PageNavbar />
      {settings?.layout === 'demo1' && (
        <Container>
          <PageHeader
            description={
              <>
                <div className="flex items-center gap-2 text-sm font-medium">
                  <span className="text-foreground font-medium">
                    Jayson Tatum
                  </span>
                  <Link
                    href="mailto:jaytatum@ktstudio.com"
                    className="text-secondary-foreground hover:text-primary"
                  >
                    jaytatum@ktstudio.com
                  </Link>
                  <span className="size-0.75 bg-mono/50 rounded-full"></span>
                  <Button mode="link" underlined="dashed" asChild>
                    <Link href="/account/members/team-info">Personal Info</Link>
                  </Button>
                </div>
              </>
            }
          />
        </Container>
      )}
      <Container>
        <AccountGetStartedContent />
      </Container>
    </Fragment>
  );
}
