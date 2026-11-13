'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { AC_PULL_READ } from '../components/autocount-meta';
import { FindDocumentView } from './components/find-document-view';

/**
 * AutoCount Find document (sprint-5/17, AC-DOC-FINDER) - look up any
 * AutoCount document by its number without knowing its DocDate. Gated
 * `autocount.pull.read`. Read only towards AutoCount.
 */
export default function AutocountFindDocumentPage() {
  return (
    <RequirePermission permission={AC_PULL_READ}>
      <FindDocumentView />
    </RequirePermission>
  );
}
