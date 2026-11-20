import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ideaPortalAuth } from '@/lib/idea-portal-auth';
import { ideaPortalService } from './idea-portal-service';

/** Lane IDEA-PORTAL: the service is the only door to /portal/ideas. */

function ok(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

describe('ideaPortalService', () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
    ideaPortalAuth.set('portal-token-1');
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    ideaPortalAuth.set(null);
  });

  it('sends the portal token as the Bearer', async () => {
    fetchMock.mockResolvedValue(ok({ kind: 'staff', name: 'Aiman', role: 'Staff', productId: null, canManage: false }));
    await ideaPortalService.me();
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/portal\/ideas\/me$/);
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer portal-token-1');
  });

  it('builds the feedback list query (repeatable column, flags)', async () => {
    fetchMock.mockResolvedValue(ok({ items: [], total: 0, page: 2, pageSize: 25 }));
    await ideaPortalService.list({
      q: 'order status',
      columns: ['under_review', 'closed'],
      sort: 'new',
      mine: true,
      includeClosed: true,
      page: 2,
      pageSize: 25,
    });
    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.pathname).toBe('/portal/ideas');
    expect(url.searchParams.getAll('column')).toEqual(['under_review', 'closed']);
    expect(url.searchParams.get('q')).toBe('order status');
    expect(url.searchParams.get('sort')).toBe('new');
    expect(url.searchParams.get('mine')).toBe('true');
    expect(url.searchParams.get('includeClosed')).toBe('true');
    expect(url.searchParams.get('page')).toBe('2');
  });

  it('omits false flags from the roadmap query', async () => {
    fetchMock.mockResolvedValue(ok({ columns: [] }));
    await ideaPortalService.roadmap({ mine: false, productId: null });
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/portal\/ideas\/roadmap$/);
  });

  it('a 401 clears the stored portal token (back to sign-in)', async () => {
    fetchMock.mockResolvedValue(ok({ error: { code: 'unauthorized', message: 'Sign in to continue.' } }, 401));
    await expect(ideaPortalService.roadmap()).rejects.toMatchObject({ status: 401 });
    expect(ideaPortalAuth.get()).toBeNull();
  });

  it('a 404 keeps the token', async () => {
    fetchMock.mockResolvedValue(ok({ error: { code: 'not_found', message: 'Idea not found.' } }, 404));
    await expect(ideaPortalService.get('x')).rejects.toMatchObject({ status: 404 });
    expect(ideaPortalAuth.get()).toBe('portal-token-1');
  });

});
