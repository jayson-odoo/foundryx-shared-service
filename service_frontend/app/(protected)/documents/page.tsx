'use client';

import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { DriveExplorer } from '@/components/platform/document-drive';
import { PageHeader } from '@/components/platform/page-header';

export default function DocumentsPage() {
  return (
    <RequirePermission permission="documents.read">
      <Container width="fluid">
        <PageHeader description="Organise, share and version your team’s files." />
        <DriveExplorer />
      </Container>
    </RequirePermission>
  );
}
