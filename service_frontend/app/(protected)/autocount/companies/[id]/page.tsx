'use client';

import { use } from 'react';
import { RequirePermission } from '@/components/common/require-permission';
import { AC_COMPANIES_READ } from '../../components/autocount-meta';
import { AutocountCompanyDetailView } from '../components/company-detail-view';

export default function AutocountCompanyPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  return (
    <RequirePermission permission={AC_COMPANIES_READ}>
      <AutocountCompanyDetailView companyId={id} />
    </RequirePermission>
  );
}
