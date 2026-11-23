'use client';

/**
 * The done toast after the product dialog saves, with the Foundryx UIUX
 * switch on (slice W1-PRODUCTS, mock note "Saving shows a toast ... with
 * Undo"): "Barcode scanner saved" / "Barcode scanner added", by whom and at
 * what time. An edit gets Undo, which writes the product back as it was when
 * the dialog opened (and its software delivery settings, where the API can
 * put them back). Returns null with the switch off, so the page keeps its
 * plain toast.
 */
import { useCallback } from 'react';
import { useSession } from 'next-auth/react';
import { useFx } from '@/hooks/use-fx';
import { useDatetime } from '@/hooks/use-datetime';
import { toast } from '@/lib/toast';
import { productService } from '@/services/productService';
import { productRestorePayload } from './product-fx';
import type { ProductSaveResult } from './use-product-form';

export function useFxProductSavedToast(
  reload: () => void,
): ((result: ProductSaveResult) => void) | null {
  const fx = useFx();
  const { data: session } = useSession();
  const { formatTime } = useDatetime();
  const userName = session?.user?.name ?? undefined;

  const show = useCallback(
    ({ saved, before, deliveryBefore }: ProductSaveResult) => {
      const at = formatTime(new Date().toISOString());
      const byWhom = userName ? `${userName} at ${at}` : undefined;
      // A delivery change the API cannot put back means no Undo at all,
      // rather than an Undo that only half undoes.
      const canUndo = Boolean(before) && deliveryBefore !== null;
      toast.fxDone({
        what: `${saved.name} ${before ? 'saved' : 'added'}`,
        byWhom,
        undo:
          canUndo && before
            ? () => {
                void (async () => {
                  try {
                    await productService.updateProduct(before.id, productRestorePayload(before));
                    if (deliveryBefore && Object.keys(deliveryBefore).length > 0) {
                      await productService.setDelivery(before.id, deliveryBefore);
                    }
                    reload();
                    toast.fxDone({ what: `${before.name} put back as it was`, byWhom: userName });
                  } catch (e) {
                    toast.error(e instanceof Error ? e.message : 'Could not undo the change.');
                  }
                })();
              }
            : undefined,
      });
    },
    [formatTime, reload, userName],
  );

  return fx ? show : null;
}
