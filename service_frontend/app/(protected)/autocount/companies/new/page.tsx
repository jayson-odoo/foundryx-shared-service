'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { AC_COMPANIES_MANAGE } from '../../components/autocount-meta';
import { ConnectCompanyView } from '../components/connect-company-view';

export default function ConnectAutocountCompanyPage() {
  return (
    <RequirePermission permission={AC_COMPANIES_MANAGE}>
      <ConnectCompanyView />
    </RequirePermission>
  );
}
