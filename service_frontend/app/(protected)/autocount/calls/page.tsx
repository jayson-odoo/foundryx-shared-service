'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { AC_SYNC_READ } from '../components/autocount-meta';
import { CallsView } from './components/calls-view';

/** AutoCount calls (plan 63) - every call SS makes to AutoCount, with who caused it. Gated `autocount.sync.read`. */
export default function AutocountCallsPage() {
  return (
    <RequirePermission permission={AC_SYNC_READ}>
      <CallsView />
    </RequirePermission>
  );
}
