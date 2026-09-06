'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { TeamFormView } from '../components/team-form-view';

export default function NewTeamPage() {
  return (
    <RequirePermission permission="teams.manage">
      <TeamFormView initialEditing />
    </RequirePermission>
  );
}
