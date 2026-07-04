/**
 * Mock portal surface service (Cluster E, slice 0b) — used by Vitest to drive
 * the unified-dashboard composition + filter tests with no backend.
 */
import type {
  PortalSurface,
  PortalSurfaceService,
} from './portal-surface-service';

export const MOCK_SURFACES: PortalSurface[] = [
  {
    key: 'my_submissions',
    label: 'My Submissions',
    gatingPermission: 'my_submissions.read',
    module: 'ems',
    sortOrder: 10,
    description: 'The Profile’s own submissions and their status',
    contexts: [
      { scopeType: 'project', scopeId: 'proj-1', label: 'Annual Summit' },
      { scopeType: 'project', scopeId: 'proj-2', label: 'Spring Workshop' },
    ],
  },
  {
    key: 'my_reviews',
    label: 'My Reviews',
    gatingPermission: 'my_reviews.read',
    module: 'ems',
    sortOrder: 20,
    description: 'Reviews assigned to the Profile',
    contexts: [{ scopeType: 'project', scopeId: 'proj-1', label: 'Annual Summit' }],
  },
];

export const mockPortalSurfaceService: PortalSurfaceService = {
  async listSurfaces() {
    return MOCK_SURFACES;
  },
};
