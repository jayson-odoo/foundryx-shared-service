/**
 * Embed-connection service - the boundary the UI talks to (via hooks/configs).
 * The barrel binds the REAL api-client implementation; the mock (`*.mock.ts`) is
 * retained for tests + frontend-first iteration. The interface IS the backend
 * contract (PLAN-ideation-embed-sso §7, AC-E-5/12 - the admin registry the host
 * apps allowed to embed a tenant's Ideas workspace are registered in).
 *
 * Enforced layering: UI → hooks/configs → this service → lib/api-client → FastAPI.
 */
import type { EmbedConnectionCreateInput, EmbedConnectionItem } from '@/types/embed-connection';
import { realEmbedConnectionService } from './embed-connection-service.real';

export interface EmbedConnectionService {
  /** All embed connections for the caller's tenant (newest-first; masked). */
  list(): Promise<EmbedConnectionItem[]>;
  /**
   * Register (or re-save) a connection. The signing secret rides the payload and
   * is Fernet-encrypted at rest; it is NEVER returned - the caller reveals its
   * own copy once. Idempotent by `connectionId`.
   */
  create(input: EmbedConnectionCreateInput): Promise<EmbedConnectionItem>;
  /**
   * Rotate the signing secret (new secret only - origins/scope/active unchanged).
   * Invalidates every assertion signed with the old secret. Never returns the
   * secret; the caller reveals its own copy once.
   */
  rotate(connectionId: string, signingSecret: string): Promise<EmbedConnectionItem>;
  /** Enable/disable without re-supplying the secret. */
  setActive(connectionId: string, isActive: boolean): Promise<EmbedConnectionItem>;
  /** Hard-delete a connection (off-boarding). */
  remove(connectionId: string): Promise<void>;
}

// Real api-client implementation (mock retained in *.mock.ts for tests).
export const embedConnectionService: EmbedConnectionService = realEmbedConnectionService;
