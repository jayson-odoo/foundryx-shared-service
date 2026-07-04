/**
 * Persona service (Cluster E, slice 0b — AC-06-26). Staff-side boundary for the
 * persona-management UI: persona CRUD, portal-key grant editing, and assigning
 * personas to Profiles. Talks to the `ems` module routers via the STAFF session
 * (lib/api-client). The interface IS the backend contract:
 *
 *   GET/POST/PATCH/DELETE /ems/personas
 *   GET  /ems/personas/portal-permissions
 *   GET/PUT /ems/personas/{id}/permissions
 *   GET/POST /ems/profiles/{id}/personas, DELETE /ems/profiles/{id}/personas/{membershipId}
 *   POST /ems/profiles/{id}/invite  (staff "Send portal invite", AC-06-15c)
 *
 * Phase B binds the REAL impl (bottom). The mock is retained for Vitest.
 */
import { realPersonaService } from './persona-service.real';
import type {
  Persona,
  PersonaInput,
  PersonaMembership,
  PersonaMembershipInput,
  PersonaPatch,
  PortalInviteInput,
  PortalInviteResult,
  PortalPermission,
} from '@/types/persona';

export interface PersonaService {
  list(): Promise<Persona[]>;
  get(id: string): Promise<Persona>;
  create(body: PersonaInput): Promise<Persona>;
  update(id: string, body: PersonaPatch): Promise<Persona>;
  remove(id: string): Promise<void>;
  /** The grantable portal-permission catalog (for the grant editor). */
  portalPermissions(): Promise<PortalPermission[]>;
  getPermissions(id: string): Promise<string[]>;
  setPermissions(id: string, keys: string[]): Promise<string[]>;
  /** Persona memberships on a Profile (the staff assign path). */
  listProfileMemberships(profileId: string): Promise<PersonaMembership[]>;
  assignMembership(
    profileId: string,
    body: PersonaMembershipInput,
  ): Promise<PersonaMembership>;
  revokeMembership(profileId: string, membershipId: string): Promise<void>;
  /** Staff-driven portal invite (set-password link, optional persona grant). */
  sendPortalInvite(
    profileId: string,
    body?: PortalInviteInput,
  ): Promise<PortalInviteResult>;
}

// Phase B swap — mock retained in persona-service.mock.ts for tests.
export const personaService: PersonaService = realPersonaService;
