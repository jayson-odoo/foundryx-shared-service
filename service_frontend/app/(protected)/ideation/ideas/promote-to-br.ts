'use client';

import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { businessRequirementService } from '@/services/business-requirement-service';
import { brFormHref } from '@/app/(protected)/ideation/business-requirements/components/paths';
import type { Idea } from '@/types/ideation';

type Router = ReturnType<typeof useRouter>;

export interface PromoteOptions {
  /** Cluster label → the new BR's title (AC-BI-32b). Omitted for a single-idea /
   * bulk promote — the backend derives the title from the representative idea's
   * problem so the BR is never "Untitled BR". */
  title?: string;
}

/**
 * Promote a set of ideas to a NEW draft BR and land on its Grill tab (AC-BI-32 /
 * 32b). All ideas must share ONE product (a BR links same-product ideas,
 * AC-BI-17). The BR absorbs the idea (warm start): its problem_statement is
 * pre-filled server-side and the grill auto-opens on arrival (AC-BI-29b).
 *
 * Shared by every promote surface — the ideas-list row/bulk menu, the cluster
 * suggestions, and the idea form/detail view — so the flow stays identical.
 */
export async function promoteIdeasToBr(
  ideas: Idea[],
  router: Router,
  opts: PromoteOptions = {},
): Promise<void> {
  if (ideas.length === 0) return;
  const productIds = new Set(ideas.map((i) => i.productId));
  if (productIds.size > 1) {
    toast.error('Select ideas from a single product to promote them together.');
    return;
  }
  try {
    const created = await businessRequirementService.create({
      productId: ideas[0].productId,
      ideaIds: ideas.map((i) => i.id),
      ...(opts.title ? { title: opts.title } : {}),
    });
    toast.success('Draft requirement created — start grilling.');
    router.push(brFormHref(created.id, { tab: 'grill' }));
  } catch (e) {
    toast.error(
      e instanceof Error ? e.message : 'Could not promote to a business requirement.',
    );
  }
}
