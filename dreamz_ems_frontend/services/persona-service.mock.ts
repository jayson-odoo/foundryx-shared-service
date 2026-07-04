/**
 * Mock persona service (Cluster E, slice 0b) — used by Vitest to drive the
 * persona-management UI tests with no backend.
 */
import type { Persona, PortalPermission } from '@/types/persona';
import type { PersonaService } from './persona-service';

export const MOCK_PERSONAS: Persona[] = [
  {
    id: 'p-participant',
    key: 'participant',
    label: 'Participant',
    description: 'Event participant',
    isSystem: true,
    sortOrder: 10,
    createdAt: '2026-06-21T00:00:00Z',
  },
  {
    id: 'p-reviewer',
    key: 'reviewer',
    label: 'Reviewer',
    description: 'Peer reviewer',
    isSystem: true,
    sortOrder: 20,
    createdAt: '2026-06-21T00:00:00Z',
  },
  {
    id: 'p-custom',
    key: 'sponsor',
    label: 'Sponsor',
    description: null,
    isSystem: false,
    sortOrder: 30,
    createdAt: '2026-06-21T00:00:00Z',
  },
];

export const MOCK_PORTAL_PERMISSIONS: PortalPermission[] = [
  { key: 'my_submissions.read', label: 'My Submissions (portal)', description: '' },
  { key: 'my_reviews.read', label: 'My Reviews (portal)', description: '' },
  { key: 'decisions.read', label: 'Decisions (portal)', description: '' },
];

export const mockPersonaService: PersonaService = {
  async list() {
    return MOCK_PERSONAS;
  },
  async get(id) {
    const found = MOCK_PERSONAS.find((p) => p.id === id);
    if (!found) throw new Error('Not found');
    return found;
  },
  async create(body) {
    return {
      id: 'p-new',
      key: body.key,
      label: body.label ?? body.key,
      description: body.description ?? null,
      isSystem: false,
      sortOrder: body.sortOrder ?? 0,
      createdAt: '2026-06-21T00:00:00Z',
    };
  },
  async update(id, body) {
    const base = MOCK_PERSONAS.find((p) => p.id === id) ?? MOCK_PERSONAS[0];
    return { ...base, ...body };
  },
  async remove() {},
  async portalPermissions() {
    return MOCK_PORTAL_PERMISSIONS;
  },
  async getPermissions() {
    return ['my_submissions.read'];
  },
  async setPermissions(_id, keys) {
    return keys;
  },
  async listProfileMemberships() {
    return [];
  },
  async assignMembership(profileId, body) {
    return {
      id: 'm-new',
      profileId,
      personaId: body.personaId,
      scopeType: body.scopeType ?? 'tenant',
      scopeId: body.scopeId ?? null,
      grantedVia: 'STAFF',
      createdAt: '2026-06-21T00:00:00Z',
    };
  },
  async revokeMembership() {},
  async sendPortalInvite() {
    return { sent: true, email: 'mock@e2e.com' };
  },
};
