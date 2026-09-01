/**
 * Status-engine service boundary (sprint-2/01). UI → hook → service →
 * lib/api-client → FastAPI. Swap point per the layering ADR.
 */
import type {
  CreateStatusInput,
  CreateTransitionInput,
  SimulateResult,
  StatusEntity,
  StatusGraph,
  StatusNodeData,
  StatusTransition,
  UpdateStatusInput,
  UpdateTransitionInput,
} from '@/types/status-engine';
import { realStatusEngineService } from './status-engine-service.real';

export interface StatusEngineService {
  entities(): Promise<StatusEntity[]>;
  /** `scopeId` = scoped machines (sprint-3/01 D4) - one graph per owning record. */
  graph(entityType: string, scopeId?: string): Promise<StatusGraph>;
  createStatus(input: CreateStatusInput): Promise<StatusNodeData>;
  updateStatus(id: string, input: UpdateStatusInput): Promise<StatusNodeData>;
  deleteStatus(id: string): Promise<void>;
  setStatusActive(id: string, active: boolean): Promise<StatusNodeData>;
  migrateRecords(id: string, toStatusId: string): Promise<{ migrated: number }>;
  reorder(entityType: string, orderedIds: string[]): Promise<StatusGraph>;
  createTransition(input: CreateTransitionInput): Promise<StatusTransition>;
  updateTransition(id: string, input: UpdateTransitionInput): Promise<StatusTransition>;
  deleteTransition(id: string): Promise<void>;
  /** Admin date-simulation (sprint-4/03 Slice 6): run the entity's time sweep
   * as-of a date. `apply=false` (default) previews; `apply=true` commits. */
  simulate(entityType: string, asOf: string, apply: boolean): Promise<SimulateResult>;
}

export const statusEngineService: StatusEngineService = realStatusEngineService;
