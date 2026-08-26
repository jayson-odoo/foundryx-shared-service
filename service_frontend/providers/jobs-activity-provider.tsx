'use client';

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { JobsDrawer } from '@/components/platform/jobs-drawer';
import { StorageMigrationWizard } from '@/components/platform/storage-migration-wizard';
import { useJobs } from '@/hooks/use-jobs';
import { JOB_IN_FLIGHT, type Job } from '@/types/jobs';

interface JobsActivityContextValue {
  /** Open the generic Jobs activity drawer. */
  setDrawerOpen: (open: boolean) => void;
  drawerOpen: boolean;
  /** Open the storage-migration wizard. */
  openMigration: () => void;
  jobs: Job[];
  /** In-flight job count (drives the header trigger badge). */
  activeCount: number;
  refresh: () => Promise<void>;
}

const Ctx = createContext<JobsActivityContextValue | null>(null);

/**
 * Jobs activity provider (sprint-4/10) - holds the generic Jobs drawer + the
 * storage-migration wizard at the layout root (sibling of the Uploads/Downloads/
 * Imports providers), so the header can trigger the drawer and any storage
 * connection's "Migrate storage" action can open the wizard. Polls the job list
 * while anything is in flight.
 */
export function JobsActivityProvider({ children }: { children: ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [migrationOpen, setMigrationOpen] = useState(false);
  const { jobs, refresh } = useJobs();

  const openMigration = useCallback(() => setMigrationOpen(true), []);
  const activeCount = jobs.filter((j) => JOB_IN_FLIGHT.has(j.status)).length;

  const value = useMemo(
    () => ({ setDrawerOpen, drawerOpen, openMigration, jobs, activeCount, refresh }),
    [drawerOpen, openMigration, jobs, activeCount, refresh],
  );

  return (
    <Ctx.Provider value={value}>
      {children}
      <JobsDrawer open={drawerOpen} onOpenChange={setDrawerOpen} jobs={jobs} />
      <StorageMigrationWizard
        open={migrationOpen}
        onClose={() => setMigrationOpen(false)}
        onStarted={() => {
          void refresh();
          setDrawerOpen(true);
        }}
      />
    </Ctx.Provider>
  );
}

export function useJobsActivity(): JobsActivityContextValue {
  const ctx = useContext(Ctx);
  if (!ctx) {
    return {
      setDrawerOpen: () => {},
      drawerOpen: false,
      openMigration: () => {},
      jobs: [],
      activeCount: 0,
      refresh: async () => {},
    };
  }
  return ctx;
}
