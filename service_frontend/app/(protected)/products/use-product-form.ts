'use client';

import { useEffect, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { BUILD_REPO_ERROR, isValidBuildRepo } from '@/lib/build-repo';
import {
  productService,
  type DeliveryConfigInput,
  type Product,
  type ProductKind,
} from '@/services/productService';

export const SOFTWARE_KIND = 'software';
// A product's feedback board colour (lane SS-MULTI-PRODUCT-BOARD); the
// backend applies the same rule (422 with fieldErrors.boardColor).
export const BOARD_COLOR_RE = /^#[0-9a-f]{6}$/;
const BOARD_COLOR_ERROR = 'Enter the colour as #rrggbb.';

/** Parse a money input to a number, or null when blank/invalid. */
export function toMoney(raw: string): number | null {
  const t = raw.trim();
  if (t.length === 0) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

/**
 * What a save did, for the caller's done message. `before` is the product as
 * it was when an edit opened; `deliveryBefore` is the delivery body that puts
 * a changed software delivery config back, or `null` when that change cannot
 * be put back (a domain base set where there was none: the API cannot clear
 * it).
 */
export interface ProductSaveResult {
  saved: Product;
  before?: Product;
  deliveryBefore?: DeliveryConfigInput | null;
}

/**
 * The product dialog's state and save (shared by the dialog with the
 * Foundryx UIUX switch off and on, so both save exactly the same way).
 * Basic scalar fields map to the core `/products` contract. For a software
 * product the delivery config (GET/PUT /ideation/products/{id}/delivery) is
 * saved AFTER the product on create (needs the new id) and only when it
 * changed on edit.
 */
export function useProductForm(product: Product | undefined, kinds: ProductKind[]) {
  // A product created by THIS dialog becomes the edit target if the follow-up
  // delivery save fails, so a second Save never creates a duplicate.
  const [created, setCreated] = useState<Product | null>(null);
  const current = product ?? created;
  const isEdit = Boolean(current);

  const [name, setName] = useState(product?.name ?? '');
  const [kind, setKind] = useState<string>(
    product?.kind ?? kinds[0]?.key ?? 'service',
  );
  const [sku, setSku] = useState(product?.sku ?? '');
  const [defaultPrice, setDefaultPrice] = useState(
    product?.defaultPrice != null ? String(product.defaultPrice) : '',
  );
  const [tax, setTax] = useState(product?.tax != null ? String(product.tax) : '');
  const [currency, setCurrency] = useState(product?.currency ?? '');
  const [uom, setUom] = useState(product?.uom ?? '');
  const [isActive, setIsActive] = useState(product?.isActive ?? true);

  // Software-only delivery config (product-domain base).
  const [domainBase, setDomainBase] = useState('');
  const [initialDomainBase, setInitialDomainBase] = useState<string | null>(null);
  const [buildRepo, setBuildRepo] = useState('');
  const [initialBuildRepo, setInitialBuildRepo] = useState('');
  const [buildRepoError, setBuildRepoError] = useState<string | null>(null);
  // Feedback board look (lane SS-MULTI-PRODUCT-BOARD): one colour + a name.
  const [boardColor, setBoardColor] = useState('');
  const [initialBoardColor, setInitialBoardColor] = useState('');
  const [boardName, setBoardName] = useState('');
  const [initialBoardName, setInitialBoardName] = useState('');
  const [boardColorError, setBoardColorError] = useState<string | null>(null);
  const [deliveryLoading, setDeliveryLoading] = useState(false);
  const [deliveryError, setDeliveryError] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isSoftware = kind === SOFTWARE_KIND;

  // On edit of an existing software product, load its delivery config so the
  // field prefills. A 403 (caller lacks ideation.products.manage) degrades to a
  // read-only note rather than blocking the whole form.
  useEffect(() => {
    if (!isEdit || !product || product.kind !== SOFTWARE_KIND) return;
    let cancelled = false;
    setDeliveryLoading(true);
    setDeliveryError(null);
    productService
      .getDelivery(product.id)
      .then((cfg) => {
        if (cancelled) return;
        setDomainBase(cfg.productDomainBase ?? '');
        setInitialDomainBase(cfg.productDomainBase ?? '');
        setBuildRepo(cfg.buildRepo ?? '');
        setInitialBuildRepo(cfg.buildRepo ?? '');
        setBoardColor(cfg.boardColor ?? '');
        setInitialBoardColor(cfg.boardColor ?? '');
        setBoardName(cfg.boardName ?? '');
        setInitialBoardName(cfg.boardName ?? '');
      })
      .catch((e) => {
        if (cancelled) return;
        setDeliveryError(
          e instanceof Error ? e.message : 'Could not load the delivery config.',
        );
      })
      .finally(() => {
        if (!cancelled) setDeliveryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isEdit, product]);

  const valid = name.trim().length > 0 && kind.trim().length > 0;

  const kindOptions = kinds.map((k) => ({ label: k.label, value: k.key }));

  const handleSave = async (
    onSaved: (result: ProductSaveResult) => void,
    onClose: () => void,
  ) => {
    if (!valid) return;
    // Add mode only: catch a bad repo BEFORE createProduct runs (no orphan product).
    if (!isEdit && isSoftware && buildRepo.trim().length > 0 && !isValidBuildRepo(buildRepo.trim())) {
      setBuildRepoError(BUILD_REPO_ERROR);
      return;
    }
    const color = boardColor.trim().toLowerCase();
    if (isSoftware && color.length > 0 && !BOARD_COLOR_RE.test(color)) {
      setBoardColorError(BOARD_COLOR_ERROR);
      return;
    }
    setSaving(true);
    setError(null);
    setBuildRepoError(null);
    setBoardColorError(null);
    try {
      const payload = {
        name: name.trim(),
        kind,
        sku: sku.trim() || null,
        defaultPrice: toMoney(defaultPrice),
        tax: toMoney(tax),
        currency: currency.trim() || null,
        uom: uom.trim() || null,
        isActive,
      };

      const saved = current
        ? await productService.updateProduct(current.id, payload)
        : await productService.createProduct(payload);
      if (!current) setCreated(saved);

      // Persist the software delivery base when applicable. On create we always
      // write a provided base; on edit only when it actually changed.
      let deliveryBefore: DeliveryConfigInput | null | undefined;
      if (isSoftware) {
        const trimmed = domainBase.trim();
        const repo = buildRepo.trim();
        const domainChanged = isEdit ? trimmed !== (initialDomainBase ?? '') : trimmed.length > 0;
        const repoChanged = isEdit ? repo !== initialBuildRepo : repo.length > 0;
        const board = boardName.trim();
        const colorChanged = color !== initialBoardColor;
        const nameChanged = board !== initialBoardName;
        const body: DeliveryConfigInput = {};
        if ((domainChanged && trimmed.length > 0) || repoChanged) {
          // productDomainBase is sent only when set: a product with just a build
          // repository must not be forced to carry a domain base.
          if (trimmed.length > 0) body.productDomainBase = trimmed;
          body.buildRepo = repo.length > 0 ? repo : null;
        }
        // Board look: sent only when changed (omitted = untouched, null clears).
        if (colorChanged) body.boardColor = color.length > 0 ? color : null;
        if (nameChanged) body.boardName = board.length > 0 ? board : null;
        if (Object.keys(body).length > 0) {
          await productService.setDelivery(saved.id, body);
          deliveryBefore = deliveryRestoreBody(body, {
            domainBase: initialDomainBase ?? '',
            buildRepo: initialBuildRepo,
            boardColor: initialBoardColor,
            boardName: initialBoardName,
          });
        }
      }

      onSaved({ saved, before: product, deliveryBefore });
      onClose();
    } catch (e) {
      const fieldErrors =
        e instanceof ApiError && e.status === 422
          ? (e.detail as { fieldErrors?: Record<string, string> } | undefined)?.fieldErrors
          : undefined;
      // FastAPI's own pattern 422 arrives as a message naming the field.
      const repoMessage =
        fieldErrors?.buildRepo ??
        (e instanceof ApiError && e.status === 422 && /buildRepo/i.test(e.message)
          ? e.message
          : undefined);
      if (fieldErrors?.boardColor) {
        setBoardColorError(fieldErrors.boardColor);
        setSaving(false);
        return;
      }
      if (repoMessage) {
        setBuildRepoError(repoMessage);
        setSaving(false);
        return;
      }
      setError(e instanceof Error ? e.message : 'Could not save the product.');
      setSaving(false);
    }
  };

  return {
    isEdit,
    isSoftware,
    valid,
    kindOptions,
    name,
    setName,
    kind,
    setKind,
    sku,
    setSku,
    defaultPrice,
    setDefaultPrice,
    tax,
    setTax,
    currency,
    setCurrency,
    uom,
    setUom,
    isActive,
    setIsActive,
    domainBase,
    setDomainBase,
    buildRepo,
    setBuildRepo,
    buildRepoError,
    setBuildRepoError,
    boardColor,
    setBoardColor,
    boardColorError,
    setBoardColorError,
    boardName,
    setBoardName,
    deliveryLoading,
    deliveryError,
    saving,
    error,
    handleSave,
  };
}

/**
 * The delivery body that puts back what `sent` changed, or null when it
 * cannot: the API has no way to clear a domain base, so a base set where
 * there was none cannot be undone.
 */
export function deliveryRestoreBody(
  sent: DeliveryConfigInput,
  initial: { domainBase: string; buildRepo: string; boardColor: string; boardName: string },
): DeliveryConfigInput | null {
  const back: DeliveryConfigInput = {};
  if ('productDomainBase' in sent || 'buildRepo' in sent) {
    if (sent.productDomainBase !== undefined && initial.domainBase.length === 0) return null;
    if (initial.domainBase.length > 0) back.productDomainBase = initial.domainBase;
    back.buildRepo = initial.buildRepo.length > 0 ? initial.buildRepo : null;
  }
  if ('boardColor' in sent) back.boardColor = initial.boardColor.length > 0 ? initial.boardColor : null;
  if ('boardName' in sent) back.boardName = initial.boardName.length > 0 ? initial.boardName : null;
  return back;
}
