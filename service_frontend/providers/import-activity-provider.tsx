'use client';

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { ImportModal } from '@/components/platform/import-wizard/import-modal';
import { ImportsDrawer } from '@/components/platform/import-wizard/imports-drawer';
import { useImportJobs } from '@/hooks/use-import-jobs';
import type { ImportJob } from '@/types/import';

export interface OpenImportOptions {
  entityType: string;
  context?: Record<string, unknown>;
}

interface ImportActivityContextValue {
  openImport: (opts: OpenImportOptions) => void;
  drawerOpen: boolean;
  setDrawerOpen: (open: boolean) => void;
  jobs: ImportJob[];
  activeCount: number;
  refresh: () => Promise<void>;
}

const Ctx = createContext<ImportActivityContextValue | null>(null);

const IN_FLIGHT = new Set(['pending', 'validating', 'importing']);

/**
 * Import activity provider (sprint-3/09 D9) - holds the wizard modal + the
 * Imports activity drawer (top-bar trigger, sibling of Uploads/Downloads) at
 * the layout level so any ResourceList's Import button can trigger the flow and
 * every import is trackable from the header.
 */
export function ImportActivityProvider({ children }: { children: ReactNode }) {
  const [modal, setModal] = useState<OpenImportOptions | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const { jobs, refresh } = useImportJobs();

  const openImport = useCallback((opts: OpenImportOptions) => setModal(opts), []);
  const activeCount = jobs.filter((j) => IN_FLIGHT.has(j.status)).length;

  const value = useMemo(
    () => ({ openImport, drawerOpen, setDrawerOpen, jobs, activeCount, refresh }),
    [openImport, drawerOpen, jobs, activeCount, refresh],
  );

  return (
    <Ctx.Provider value={value}>
      {children}
      {modal && (
        <ImportModal
          entityType={modal.entityType}
          context={modal.context}
          onClose={() => setModal(null)}
        />
      )}
      <ImportsDrawer />
    </Ctx.Provider>
  );
}

export function useImportActivity(): ImportActivityContextValue {
  const ctx = useContext(Ctx);
  if (!ctx) {
    return {
      openImport: () => {},
      drawerOpen: false,
      setDrawerOpen: () => {},
      jobs: [],
      activeCount: 0,
      refresh: async () => {},
    };
  }
  return ctx;
}
