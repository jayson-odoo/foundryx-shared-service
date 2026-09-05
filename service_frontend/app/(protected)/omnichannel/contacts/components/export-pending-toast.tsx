import { toast } from 'sonner';

/**
 * D-A2-6a fallback: the export job hasn't finished inside the short wait
 * window. Never a silent failure - point the user at the Jobs surface, where
 * it keeps running and can be downloaded once done (AC-CTM-10).
 */
export function exportPendingToast(): void {
  toast.info('The export is still running - it will finish in Jobs.', {
    action: {
      label: 'View Jobs',
      onClick: () => {
        if (typeof window !== 'undefined') window.location.assign('/jobs');
      },
    },
  });
}
