/**
 * Grill service — the boundary the Grill tab talks to (Phase B-i slice 3). The
 * interface IS the backend contract (modules/ideation/routers/grill.py).
 *
 * Enforced layering: UI → hooks → this service → lib/api-client → FastAPI.
 * Frontend-first built against `.mock`; the boundary is swapped to `.real`
 * below (the ONE line). The mock is retained only for tests.
 */
import type { GrillGenerate, GrillState, GrillTurn } from '@/types/grill';
import { realGrillService } from './grill-service.real';

export interface GrillService {
  /** The transcript + coverage + readiness for a BR's grill (AC-BI-29). */
  state(brId: string): Promise<GrillState>;
  /** Send one human turn → prose reply + coverage map (AC-BI-24b). Synchronous. */
  turn(brId: string, message: string): Promise<GrillTurn>;
  /** Extract answers from the whole transcript → persist (BR stays draft). */
  generate(brId: string): Promise<GrillGenerate>;
}

export const grillService: GrillService = realGrillService;
