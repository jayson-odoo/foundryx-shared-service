'use client';

import Link from 'next/link';
import { useSettings } from '@/providers/settings-provider';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { AccountActivityContent } from '@/app/(protected)/account/activity/content';
import { PageNavbar } from '@/app/(protected)/account/page-navbar';

export default function AccountActivityPage() {
  const { settings } = useSettings();

  return (
    <>
      <PageNavbar />
      {settings.layout === 'demo1' && (
        <Container>
          <PageHeader
            description="Central Hub for Personal Customization"
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline" asChild>
                  <Link href="#">Privacy Settings</Link>
                </Button>
              </div>
            }
          />
        </Container>
      )}
      <Container>
        <AccountActivityContent />
      </Container>
    </>
  );
}
