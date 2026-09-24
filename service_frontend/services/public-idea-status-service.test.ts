import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * S5 public idea status service (AC-1601). TEST-FIRST (PRINCIPLES.md):
 * written before the service exists. Mirrors the `ideation-service.real.test.ts`
 * mocking style (mock `publicFetch` off `@/lib/api-client`, keep the real
 * `ApiError`) - a pre-auth surface, so this rides `publicFetch` (no Bearer),
 * NOT `apiFetch`.
 */

const { publicFetch } = vi.hoisted(() => ({ publicFetch: vi.fn() }));

vi.mock('@/lib/api-client', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api-client')>('@/lib/api-client');
  return { ...actual, publicFetch };
});

// Imported AFTER the mock is registered.
import { ApiError } from '@/lib/api-client';
import { publicIdeaStatusService } from './public-idea-status-service';

beforeEach(() => vi.clearAllMocks());

describe('publicIdeaStatusService', () => {
  it('resolves via GET /public/ideas/<token> (no bearer - publicFetch, not apiFetch)', async () => {
    publicFetch.mockResolvedValue({
      title: 'Show promo price in red on price tags',
      status: 'New',
      ideaNumber: 'IDEA-0182',
    });
    const result = await publicIdeaStatusService.resolve('tok_abc123def456');
    expect(publicFetch).toHaveBeenCalledWith('/public/ideas/tok_abc123def456');
    expect(result).toEqual({
      title: 'Show promo price in red on price tags',
      status: 'New',
      ideaNumber: 'IDEA-0182',
    });
  });

  it('URL-encodes the token', async () => {
    publicFetch.mockResolvedValue({ title: null, status: 'New', ideaNumber: 'IDEA-0002' });
    await publicIdeaStatusService.resolve('weird token/../x');
    expect(publicFetch).toHaveBeenCalledWith(
      `/public/ideas/${encodeURIComponent('weird token/../x')}`,
    );
  });

  it('returns null on a uniform 404 (unknown/malformed/draft token)', async () => {
    // The rejection is constructed INSIDE the implementation, invoked only
    // when `resolve` actually awaits `publicFetch` - building it eagerly via
    // `mockRejectedValue(new ApiError(...))` creates an already-rejected
    // promise at mock-setup time, which vitest 2.1.9 + tinyspy can flag as
    // an unhandled rejection before the `await` below ever attaches.
    publicFetch.mockImplementationOnce(() =>
      Promise.reject(new ApiError('Not found.', 404, null, undefined)),
    );
    const result = await publicIdeaStatusService.resolve('missing-token');
    expect(result).toBeNull();
  });

  it('rethrows a non-404 error (never silently swallows a real failure)', async () => {
    let thrown: unknown;
    publicFetch.mockImplementationOnce(() => {
      thrown = new ApiError('Server error', 500, null, undefined);
      return Promise.reject(thrown);
    });
    await expect(publicIdeaStatusService.resolve('tok_abc123def456')).rejects.toBe(thrown);
  });

  it('a title-null idea still resolves (the page derives "Idea <number>")', async () => {
    publicFetch.mockResolvedValue({ title: null, status: 'New', ideaNumber: 'IDEA-0007' });
    const result = await publicIdeaStatusService.resolve('tok_xyz789');
    expect(result?.title).toBeNull();
    expect(result?.ideaNumber).toBe('IDEA-0007');
  });
});
