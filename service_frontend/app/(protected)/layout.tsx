'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useSession } from 'next-auth/react';
import { ScreenLoader } from '@/components/common/screen-loader';
import { ImpersonationBanner } from '@/components/impersonation/impersonation-banner';
import {
  DownloadsProvider,
  MyDownloadsDrawer,
  UploadActivityDrawer,
  UploadManagerProvider,
} from '@/components/platform/document-drive';
import { useSessionSync } from '@/hooks/use-session-sync';
import { ImportActivityProvider } from '@/providers/import-activity-provider';
import { JobsActivityProvider } from '@/providers/jobs-activity-provider';
import { Demo1Layout } from '../components/layouts/demo1/layout';

export default function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { data: session, status } = useSession();
  const router = useRouter();
  // Session freshness (plan 06 D8): every hard page load reconciles the
  // session (permissions/roles/identity) with the backend - update-on-drift
  // only, so this can't loop the loading state below.
  useSessionSync();

  useEffect(() => {
    if (status === 'unauthenticated') {
      router.push('/signin');
    }
  }, [status, router]);

  if (status === 'loading') {
    return <ScreenLoader />;
  }

  return session ? (
    // Upload + download activity are app-wide (any feature can enqueue them -
    // documents today, complaint/invoice attachments later), so the providers +
    // their drawers live at the protected-layout root and the header triggers
    // them (sprint-3/04b - universal Uploads/Downloads).
    <UploadManagerProvider>
      <DownloadsProvider>
        <ImportActivityProvider>
          <JobsActivityProvider>
            <ImpersonationBanner />
            <Demo1Layout>{children}</Demo1Layout>
            <UploadActivityDrawer />
            <MyDownloadsDrawer />
          </JobsActivityProvider>
        </ImportActivityProvider>
      </DownloadsProvider>
    </UploadManagerProvider>
  ) : null;
}
