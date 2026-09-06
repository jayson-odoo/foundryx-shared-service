import { toast } from '@/lib/toast';

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
