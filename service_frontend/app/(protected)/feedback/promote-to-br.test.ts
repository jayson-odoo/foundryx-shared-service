import { describe, expect, it, vi, beforeEach } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { Idea } from '@/types/ideation';
import type { IdeaService } from '@/services/ideation-service';
import { promoteIdeasToBr } from './promote-to-br';

/**
 * Issue #90 W2 (AC-90-211): a promote that 422s with
 * `detail.code === 'br_template_unavailable'` (the same code the dialog
 * reads, `business_requirements.py`) surfaces the SAME sentence the dialog's
 * Alert shows - "Ask an administrator to restore the Business Requirement
 * template." - not the generic create-failure toast.
 */

const create = vi.fn();
vi.mock('@/services/business-requirement-service', () => ({
  businessRequirementService: { create: (...a: unknown[]) => create(...a) },
}));

const toastError = vi.fn();
const toastSuccess = vi.fn();
vi.mock('@/lib/toast', () => ({
  toast: {
    error: (...a: unknown[]) => toastError(...a),
    success: (...a: unknown[]) => toastSuccess(...a),
  },
}));

const push = vi.fn();
const router = { push } as unknown as Parameters<typeof promoteIdeasToBr>[1];

const anIdea = (over: Partial<Idea> = {}): Idea => ({
  id: 'idea-1',
  productId: 'prod-1',
  productName: 'Sorento CRM',
  status: 'captured',
  problem: 'Export orders to Excel',
  rawText: 'raw',
  source: 'whatsapp',
  submitterName: 'Jayson',
  upvotes: 0,
  downvotes: 0,
  myVote: null,
  priority: 0,
  attachments: [],
  createdAt: '2026-07-18T00:00:00Z',
  isTest: false,
  ...over,
});

beforeEach(() => {
  create.mockReset();
  toastError.mockReset();
  toastSuccess.mockReset();
  push.mockReset();
});

describe('promoteIdeasToBr - AC-90-211 br_template_unavailable toast', () => {
  it('shows "ask an administrator" when create 422s with br_template_unavailable', async () => {
    create.mockRejectedValue(
      new ApiError('No active Business Requirement template is configured.', 422, undefined, {
        code: 'br_template_unavailable',
        message: 'No active Business Requirement template is configured.',
      }),
    );
    await promoteIdeasToBr([anIdea()], router);
    expect(toastError).toHaveBeenCalledWith(
      'Ask an administrator to restore the Business Requirement template.',
    );
    expect(push).not.toHaveBeenCalled();
  });

  it('still shows the generic failure message for any other error', async () => {
    create.mockRejectedValue(new Error('boom'));
    await promoteIdeasToBr([anIdea()], router);
    expect(toastError).toHaveBeenCalledWith('boom');
  });
});

// ── Plan 15 (AC-15-20/24) - the shared promote path serves the embed runtime ──

describe('promoteIdeasToBr - embed runtime (AC-15-24)', () => {
  const embedRuntime = (promoteToBr: unknown) =>
    ({
      mode: 'embed' as const,
      service: { promoteToBr } as unknown as IdeaService,
      paths: { listHref: '/embed/ideas', formHref: (id: string) => `/embed/ideas/${id}`, newHref: '/embed/ideas/new' },
    });

  it('calls service.promoteToBr, toasts, and does NOT navigate or use the operator BR service', async () => {
    const promoteToBr = vi.fn().mockResolvedValue({ id: 'br-1', title: 'Order export', brNumber: 'BR-0007' });
    await promoteIdeasToBr([anIdea({ id: 'a' }), anIdea({ id: 'b' })], router, {
      runtime: embedRuntime(promoteToBr),
    });
    expect(promoteToBr).toHaveBeenCalledWith(['a', 'b'], undefined);
    expect(create).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
    expect(toastSuccess).toHaveBeenCalledTimes(1);
    expect(String(toastSuccess.mock.calls[0][0])).toContain('Draft requirement created');
  });

  it('forwards an explicit title', async () => {
    const promoteToBr = vi.fn().mockResolvedValue({ id: 'br-1', title: 'T' });
    await promoteIdeasToBr([anIdea({ id: 'a' })], router, { title: 'Cluster', runtime: embedRuntime(promoteToBr) });
    expect(promoteToBr).toHaveBeenCalledWith(['a'], 'Cluster');
  });

  it('surfaces a 403 as the permission toast', async () => {
    const promoteToBr = vi.fn().mockRejectedValue(new ApiError('Forbidden', 403, undefined, { code: 'forbidden' }));
    await promoteIdeasToBr([anIdea()], router, { runtime: embedRuntime(promoteToBr) });
    expect(toastError).toHaveBeenCalledWith('You do not have permission to promote ideas.');
    expect(push).not.toHaveBeenCalled();
  });
});

describe('promoteIdeasToBr - operator runtime unchanged (AC-15-23/24)', () => {
  it('still creates via businessRequirementService and pushes to the Grill tab', async () => {
    create.mockResolvedValue({ id: 'br-9' });
    await promoteIdeasToBr([anIdea({ id: 'a' })], router, {
      runtime: {
        mode: 'operator',
        service: {} as unknown as IdeaService,
        paths: { listHref: '/ideation/ideas', formHref: (id: string) => `/ideation/ideas/${id}`, newHref: '/ideation/ideas/new' },
      },
    });
    expect(create).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledTimes(1);
    expect(String(push.mock.calls[0][0])).toContain('br-9');
    expect(String(push.mock.calls[0][0])).toContain('grill');
  });

  it('an operator 403 also shows the permission toast', async () => {
    create.mockRejectedValue(new ApiError('Forbidden', 403, undefined, { code: 'forbidden' }));
    await promoteIdeasToBr([anIdea()], router, {
      runtime: {
        mode: 'operator',
        service: {} as unknown as IdeaService,
        paths: { listHref: '/l', formHref: (id: string) => `/l/${id}`, newHref: '/l/new' },
      },
    });
    expect(toastError).toHaveBeenCalledWith('You do not have permission to promote ideas.');
  });
});
