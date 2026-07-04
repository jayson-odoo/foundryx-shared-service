'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { ConnectionFormView } from '../components/connection-form-view';

export default function NewConnectionPage() {
  return (
    <RequirePermission permission="integrations.manage">
      <ConnectionFormView initialEditing />
    </RequirePermission>
  );
}
