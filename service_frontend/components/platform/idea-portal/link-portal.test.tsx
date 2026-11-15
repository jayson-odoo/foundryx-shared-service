import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PortalPrincipal, PortalSession } from '@/types/idea-portal';

/** Lane PUBLIC-IDEAS-BOARD (AC-FB-40/41/42): the existing portal opened by a
 * dealer's personal feedback link. Service mocked at the service boundary. */

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => '/public/feedback/board/LINKTOKEN_abcdefghijklmnopqrstuvwxyz0123',
  useParams: () => ({}),
}));
vi.mock('@/hooks/use-branding', () => ({
  useTenantBranding: () => ({
    branding: { isBranded: true, tenantName: 'Tenant', appName: null, slogan: null, logoUrl: null, faviconUrl: null, illustrationUrl: null, tokens: null, version: 0 },
    isResolved: true,
  }),
}));

const svc = vi.hoisted(() => ({
  linkSession: vi.fn(),
  list: vi.fn(),
  products: vi.fn(),
  me: vi.fn(),
}));
vi.mock('@/services/idea-portal-service', () => ({ ideaPortalService: svc }));

import { linkPortalPaths, mineFilterLabel } from '@/hooks/use-idea-portal';
import { LinkPortalRoot } from './portal-root';
import { FeedbackView } from './feedback-view';

const TOKEN = 'LINKTOKEN_abcdefghijklmnopqrstuvwxyz0123';
const contact: PortalPrincipal = { kind: 'contact', name: 'Dealer', role: 'Dealer', productId: null, canManage: false };

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  svc.list.mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 25 });
  svc.products.mockResolvedValue([]);
});

describe('linkPortalPaths', () => {
  it('puts the link token in every path and lands on feedback', () => {
    const p = linkPortalPaths(TOKEN);
    expect(p.feedback).toBe(`/public/feedback/board/${TOKEN}`);
    expect(p.roadmap).toBe(`/public/feedback/board/${TOKEN}/roadmap`);
    expect(p.changelog).toBe(`/public/feedback/board/${TOKEN}/changelog`);
    expect(p.idea('IDEA-0003')).toBe(`/public/feedback/board/${TOKEN}/IDEA-0003`);
  });

  it('labels the mine toggle per viewer', () => {
    expect(mineFilterLabel(contact)).toBe('My requests');
    expect(mineFilterLabel({ ...contact, kind: 'crm' })).toBe('My feedback');
    expect(mineFilterLabel({ ...contact, kind: 'staff' })).toBeNull();
  });
});

describe('LinkPortalRoot', () => {
  it('exchanges the link once, keeps the token out of storage, shows the board', async () => {
    const session: PortalSession = { token: 'portal-jwt', principal: contact };
    svc.linkSession.mockResolvedValue(session);
    render(
      <LinkPortalRoot linkToken={TOKEN}>
        <FeedbackView />
      </LinkPortalRoot>,
    );
    expect(await screen.findByRole('button', { name: 'My requests' })).toBeInTheDocument();
    expect(svc.linkSession).toHaveBeenCalledTimes(1);
    expect(svc.linkSession).toHaveBeenCalledWith(TOKEN);
    expect(window.localStorage.length).toBe(0);
    // QB a: no submit form, no header submit / sign-out for a dealer.
    expect(screen.queryByText('Submit feedback')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search feedback')).toBeInTheDocument();
    const tabs = screen.getAllByRole('link').map((a) => a.textContent);
    expect(tabs.slice(0, 3)).toEqual(['Feedback', 'Roadmap', 'Changelog']);
  });

  it('a bad or cancelled link shows the not-valid message', async () => {
    svc.linkSession.mockRejectedValue(new Error('401'));
    render(
      <LinkPortalRoot linkToken="nope">
        <FeedbackView />
      </LinkPortalRoot>,
    );
    await waitFor(() => expect(screen.getByText('This link is not valid.')).toBeInTheDocument());
    expect(screen.queryByPlaceholderText('Search feedback')).not.toBeInTheDocument();
  });
});
