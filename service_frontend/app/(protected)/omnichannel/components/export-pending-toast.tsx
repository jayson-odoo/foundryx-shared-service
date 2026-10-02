import { toast } from '@/lib/toast';

/**
 * D-A9-4 fallback (mirrors the A2 contacts `export-pending-toast.tsx`,
 * plan 26) - the export job hasn't finished inside the short wait window.
 * Never a silent failure - point the user at the Jobs surface, where it
 * keeps running and can be downloaded once done.
 */
export function reportExportPendingToast(push: (href: string) => void): void {
  toast.info('The export is still running - it will finish in Jobs.', {
    action: {
      label: 'View Jobs',
      onClick: () => push('/jobs'),
    },
  });
}
