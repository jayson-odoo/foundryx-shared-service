import { toast } from '@/lib/toast';
import { fxExportPendingWords } from './contacts-fx';

/**
 * D-A2-6a fallback: the export job hasn't finished inside the short wait
 * window. Never a silent failure - point the user at the Jobs surface, where
 * it keeps running and can be downloaded once done (AC-CTM-10).
 *
 * Nit 21 (review round 1): navigate via the Next router, not
 * `window.location.assign` (a full page reload) - the caller already holds
 * `useRouter()` (`use-contacts-list-config.tsx`), so its `push` is threaded
 * through here rather than reaching for a global.
 */
export function exportPendingToast(push: (href: string) => void): void {
  toast.info('The export is still running - it will finish in Jobs.', {
    action: {
      label: 'View Jobs',
      onClick: () => push('/jobs'),
    },
  });
}

/**
 * Foundryx UIUX switch only (gap audit 2, "one Jobs place"): the hand-off
 * says what is still running and where it will be, and "View jobs" opens the
 * one Jobs sheet in the top bar instead of leaving the page. `count` is the
 * ticked rows, else the list's matching total (null while unknown).
 */
export function fxExportPendingToast(count: number | null, openJobs: () => void): void {
  toast.info(fxExportPendingWords(count), {
    action: {
      label: 'View jobs',
      onClick: openJobs,
    },
  });
}
