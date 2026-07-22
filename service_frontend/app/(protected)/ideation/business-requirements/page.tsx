'use client';

import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { BrView } from './br-view';

export default function BusinessRequirementsPage() {
  return (
    <RequirePermission permission="ideation.business_requirements.read">
      <Container width="fluid">
        <BrView />
      </Container>
    </RequirePermission>
  );
}
