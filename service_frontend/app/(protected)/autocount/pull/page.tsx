'use client';

import { RequirePermission } from '@/components/common/require-permission';
import { AC_PULL_READ } from '../components/autocount-meta';
import { PullView } from './components/pull-view';

/**
 * AutoCount Pull (sprint-5/10, AC-10-38) - the human-invoked pull surface:
 * pull API keys and their snapshots. Gated `autocount.pull.read`.
 */
export default function AutocountPullPage() {
  return (
    <RequirePermission permission={AC_PULL_READ}>
      <PullView />
    </RequirePermission>
  );
}
