'use client';

import { useCallback, useEffect, useState } from 'react';
import { businessRequirementService } from '@/services/business-requirement-service';
import { ideationService } from '@/services/ideation-service';
import type {
  BusinessRequirement,
  BusinessRequirementCreateInput,
  BusinessRequirementDetail,
  BusinessRequirementStatus,
} from '@/types/business-requirement';
import type { Product } from '@/types/ideation';

/** Loads the tenant's BRs + products for the list surface, with the mutations the
 * list actions call. Client-side list (mirrors the Ideas hook) - the ResourceList
 * fetcher pages over the in-memory array. */
export function useBusinessRequirements() {
  const [brs, setBrs] = useState<BusinessRequirement[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [rows, prods] = await Promise.all([
        businessRequirementService.list({ filter: 'all' }),
        ideationService.listProducts(),
      ]);
      setBrs(rows);
      setProducts(prods);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load business requirements.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const create = useCallback(
    async (
      input: BusinessRequirementCreateInput,
    ): Promise<BusinessRequirementDetail> => {
      const created = await businessRequirementService.create(input);
      await reload();
      return created;
    },
    [reload],
  );

  const setStatus = useCallback(
    async (id: string, status: BusinessRequirementStatus) => {
      await businessRequirementService.setStatus(id, status);
      await reload();
    },
    [reload],
  );

  const remove = useCallback(
    async (id: string) => {
      await businessRequirementService.remove(id);
      await reload();
    },
    [reload],
  );

  return { brs, products, loading, error, reload, create, setStatus, remove };
}
