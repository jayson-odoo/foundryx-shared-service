'use client';

import { useEffect, useState } from 'react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { ApiError } from '@/lib/api-client';
import { BUILD_REPO_ERROR, isValidBuildRepo } from '@/lib/build-repo';
import { SearchSelect } from '@/components/platform/search-select';
import {
  productService,
  type DeliveryConfigInput,
  type Product,
  type ProductKind,
} from '@/services/productService';

const SOFTWARE_KIND = 'software';
// A product's feedback board colour (lane SS-MULTI-PRODUCT-BOARD); the
// backend applies the same rule (422 with fieldErrors.boardColor).
const BOARD_COLOR_RE = /^#[0-9a-f]{6}$/;
const BOARD_COLOR_ERROR = 'Enter the colour as #rrggbb.';

/** Parse a money input to a number, or null when blank/invalid. */
function toMoney(raw: string): number | null {
  const t = raw.trim();
  if (t.length === 0) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

/**
 * Create/Edit a catalog product (CRUD-UX standard: modal by default). Basic
 * scalar fields map to the core `/products` contract. When `kind === 'software'`
 * a **Product domain base** field appears - the absolute origin used to mint
 * ideation idea links - wired to the ideation delivery config
 * (GET/PUT /ideation/products/{id}/delivery). It is saved AFTER the product on
 * create (needs the new id) and only when it changed on edit. Every section is
 * always rendered; the software section shows a helper note.
 */
export function ProductFormDialog({
  product,
  kinds,
  onClose,
  onSaved,
}: {
  /** Edit target, or undefined for create. */
  product?: Product;
  /** Selectable kinds (software only present when Ideation is installed). */
  kinds: ProductKind[];
  onClose: () => void;
  onSaved: () => void;
}) {
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

  const handleSave = async () => {
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
        }
      }

      onSaved();
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

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit product' : 'Add product'}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? 'Update the catalog product details.'
              : 'Create a catalog product (goods, service, or software).'}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="prod-name">
              Name <span className="text-destructive">*</span>
            </Label>
            <Input
              id="prod-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Sorento CRM"
              autoFocus
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>
                Kind <span className="text-destructive">*</span>
              </Label>
              <SearchSelect
                options={kindOptions}
                value={kind}
                onChange={setKind}
                placeholder="Select a kind…"
                ariaLabel="Product kind"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="prod-sku">SKU</Label>
              <Input
                id="prod-sku"
                value={sku}
                onChange={(e) => setSku(e.target.value)}
                placeholder="Optional"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="prod-price">Default price</Label>
              <Input
                id="prod-price"
                type="number"
                step="0.01"
                min={0}
                value={defaultPrice}
                onChange={(e) => setDefaultPrice(e.target.value)}
                placeholder="0.00"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="prod-currency">Currency</Label>
              <Input
                id="prod-currency"
                value={currency}
                onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                placeholder="MYR"
                maxLength={3}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="prod-tax">Tax %</Label>
              <Input
                id="prod-tax"
                type="number"
                step="0.01"
                min={0}
                value={tax}
                onChange={(e) => setTax(e.target.value)}
                placeholder="0"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="prod-uom">Unit of measure</Label>
            <Input
              id="prod-uom"
              value={uom}
              onChange={(e) => setUom(e.target.value)}
              placeholder="e.g. unit, licence, kg"
            />
          </div>

          <div className="flex items-center justify-between rounded-md border px-3 py-2.5">
            <div>
              <Label htmlFor="prod-active" className="cursor-pointer">
                Active
              </Label>
              <p className="text-xs text-muted-foreground">
                Inactive products are hidden from selection lists.
              </p>
            </div>
            <Switch id="prod-active" checked={isActive} onCheckedChange={setIsActive} />
          </div>

          {/* Software-only delivery config - always rendered for software kind. */}
          {isSoftware && (
            <div className="space-y-1.5 rounded-md border border-dashed p-3">
              <Label htmlFor="prod-domain-base">Product domain base</Label>
              <Input
                id="prod-domain-base"
                value={domainBase}
                onChange={(e) => setDomainBase(e.target.value)}
                placeholder="https://fe-sorento.foundryx.my"
                disabled={deliveryLoading || Boolean(deliveryError)}
              />
              <p className="text-xs text-muted-foreground">
                The absolute origin of this software product&apos;s app. Feedback
                links use it (e.g. feedback captured on WhatsApp deep-links back
                here). Set it once the app has a hosted URL.
              </p>
              <Label htmlFor="prod-build-repo" className="pt-2">
                Build repository
              </Label>
              <Input
                id="prod-build-repo"
                value={buildRepo}
                onChange={(e) => {
                  setBuildRepo(e.target.value);
                  setBuildRepoError(null);
                }}
                placeholder="owner/repository"
                aria-invalid={buildRepoError ? true : undefined}
                disabled={deliveryLoading || Boolean(deliveryError)}
              />
              {buildRepoError && <p className="text-xs text-destructive">{buildRepoError}</p>}
              <Label htmlFor="prod-board-color" className="pt-2">
                Board colour
              </Label>
              <div className="flex items-center gap-2">
                <label
                  className="relative size-9 shrink-0 cursor-pointer rounded-md border border-input"
                  style={{ background: BOARD_COLOR_RE.test(boardColor.trim().toLowerCase()) ? boardColor.trim() : undefined }}
                >
                  <input
                    type="color"
                    aria-label="Pick board colour"
                    className="absolute inset-0 size-full cursor-pointer opacity-0"
                    value={BOARD_COLOR_RE.test(boardColor.trim().toLowerCase()) ? boardColor.trim().toLowerCase() : '#000000'}
                    onChange={(e) => {
                      setBoardColor(e.target.value);
                      setBoardColorError(null);
                    }}
                    disabled={deliveryLoading || Boolean(deliveryError)}
                  />
                </label>
                <Input
                  id="prod-board-color"
                  value={boardColor}
                  onChange={(e) => {
                    setBoardColor(e.target.value);
                    setBoardColorError(null);
                  }}
                  placeholder="#3b82f6"
                  aria-invalid={boardColorError ? true : undefined}
                  disabled={deliveryLoading || Boolean(deliveryError)}
                />
              </div>
              {boardColorError && <p className="text-xs text-destructive">{boardColorError}</p>}
              <Label htmlFor="prod-board-name" className="pt-2">
                Board name
              </Label>
              <Input
                id="prod-board-name"
                value={boardName}
                onChange={(e) => setBoardName(e.target.value)}
                maxLength={80}
                placeholder={name.trim() || undefined}
                disabled={deliveryLoading || Boolean(deliveryError)}
              />
              {deliveryLoading && (
                <p className="text-xs text-muted-foreground">Loading delivery config…</p>
              )}
              {deliveryError && (
                <p className="text-xs text-destructive">
                  {deliveryError} (requires the Feedback Products: Manage permission)
                </p>
              )}
            </div>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={() => void handleSave()} disabled={!valid || saving}>
            {saving ? 'Saving…' : isEdit ? 'Save changes' : 'Add product'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
