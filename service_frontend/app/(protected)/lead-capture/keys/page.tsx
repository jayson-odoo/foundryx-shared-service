'use client';

import { useCallback, useState } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { PageHeader } from '@/components/platform/page-header';
import { ResourceList } from '@/components/platform/resource-list';
import { CreateKeyDialog } from './components/create-key-dialog';
import { useLeadKeyList } from './components/use-lead-key-list';

/** Lead Capture > Keys (lane L-D, AC-64-57): the company's own gateway keys. */
export default function LeadCaptureKeysPage() {
  const [open, setOpen] = useState(false);
  const [nonce, setNonce] = useState(0);
  const onCreate = useCallback(() => setOpen(true), []);
  const config = useLeadKeyList(onCreate, nonce);

  return (
    <RequirePermission permission="lead_capture.keys.manage">
      <Container width="fluid">
        {/* Own header so Create sits on the list's toolbar row (one row:
            Search, Filters, Export, Columns, Create), like Delivery. */}
        <PageHeader />
        <ResourceList config={config} hideHeader restoreFromCtx />
      </Container>
      <CreateKeyDialog open={open} onOpenChange={setOpen} onCreated={() => setNonce((n) => n + 1)} />
    </RequirePermission>
  );
}
