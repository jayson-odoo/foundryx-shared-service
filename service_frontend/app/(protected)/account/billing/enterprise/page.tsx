'use client';

import { useSettings } from '@/providers/settings-provider';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { AccountEnterpriseContent } from '@/app/(protected)/account/billing/enterprise/content';
import { PageNavbar } from '@/app/(protected)/account/page-navbar';

export default function AccountEnterprisePage() {
  const { settings } = useSettings();

  return (
    <>
      <PageNavbar />
      {settings?.layout === 'demo1' && (
        <Container>
          <PageHeader
            description="Advanced Billing Solutions for Large Businesses"
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline">Order History</Button>
              </div>
            }
          />
        </Container>
      )}
      <Container>
        <AccountEnterpriseContent />
      </Container>
    </>
  );
}
