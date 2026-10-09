'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { MigrationFormView } from '../components/migration-form-view';

export default function NewMigrationPage() {
  return (
    <RequirePermission permission="omnichannel_migration.manage">
      <MigrationFormView />
    </RequirePermission>
  );
}
