import { describe, expect, it, vi, beforeEach } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { Idea } from '@/types/ideation';
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
