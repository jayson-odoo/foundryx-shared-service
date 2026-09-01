'use client';

import { useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { ConnectionFormView } from '../components/connection-form-view';

export default function NewConnectionPage() {
  // `?provider=` lets a module's own settings page deep-link to its connection
  // kind with the picker already answered.
  const initialProvider = useSearchParams().get('provider') ?? undefined;

  return (
    <RequirePermission permission="integrations.manage">
      <ConnectionFormView initialEditing initialProvider={initialProvider} />
    </RequirePermission>
  );
}
