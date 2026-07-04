'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { documentService } from '@/services/document-service';
import type { DownloadJob, ZipRequest } from '@/types/documents';

interface DownloadsValue {
  jobs: DownloadJob[];
  activeCount: number;
  open: boolean;
  setOpen: (open: boolean) => void;
  requestZip: (req: ZipRequest) => Promise<void>;
  download: (jobId: string) => Promise<void>;
}

const DownloadsContext = createContext<DownloadsValue | null>(null);

const POLL_MS = 2500;

export function DownloadsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<DownloadJob[]>([]);
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try {
      setJobs(await documentService.listDownloadJobs());
    } catch {
      /* non-critical */
    }
  }, []);

  // Poll only while something is in flight (stop when all settled).
  useEffect(() => {
    const inFlight = jobs.some((j) => j.status === 'pending' || j.status === 'processing');
    if (timer.current) clearTimeout(timer.current);
    if (inFlight) {
      timer.current = setTimeout(() => void refresh(), POLL_MS);
    }
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [jobs, refresh]);

  // Initial load when the drawer first opens.
  useEffect(() => {
    if (open) void refresh();
  }, [open, refresh]);

  const requestZip = useCallback(
    async (req: ZipRequest) => {
      const job = await documentService.requestZip(req);
      setJobs((prev) => [job, ...prev.filter((j) => j.id !== job.id)]);
      setOpen(true);
    },
    [],
  );

  const download = useCallback(
    async (jobId: string) => {
      const { url, filename } = await documentService.downloadJobUrl(jobId);
      // Prefer the filename we already hold from the job list (authoritative);
      // the service's object-URL path can't always recover it from headers.
      const name = jobs.find((j) => j.id === jobId)?.filename ?? filename;
      if (typeof document !== 'undefined') {
        const a = document.createElement('a');
        a.href = url;
        a.download = name;
        a.rel = 'noopener';
        a.click();
        // Free the object URL (the ZIP blob can be large) once the download has
        // started — without this every download leaks the archive for the page
        // lifetime. Delay so the browser has read the blob.
        if (url.startsWith('blob:')) setTimeout(() => URL.revokeObjectURL(url), 30_000);
      }
    },
    [jobs],
  );

  const value = useMemo<DownloadsValue>(
    () => ({
      jobs,
      activeCount: jobs.filter((j) => j.status === 'pending' || j.status === 'processing').length,
      open,
      setOpen,
      requestZip,
      download,
    }),
    [jobs, open, requestZip, download],
  );

  return <DownloadsContext.Provider value={value}>{children}</DownloadsContext.Provider>;
}

export function useDownloads(): DownloadsValue {
  const ctx = useContext(DownloadsContext);
  if (!ctx) throw new Error('useDownloads must be used within DownloadsProvider');
  return ctx;
}
