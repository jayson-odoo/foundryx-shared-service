'use client';

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
import { SearchSelect } from '@/components/platform/search-select';
import { useFx } from '@/hooks/use-fx';
import type { Product, ProductKind } from '@/services/productService';
import { FxProductFormDialog } from './fx-product-form-dialog';
import { BOARD_COLOR_RE, useProductForm, type ProductSaveResult } from './use-product-form';

export interface ProductFormDialogProps {
  /** Edit target, or undefined for create. */
  product?: Product;
  /** Selectable kinds (software only present when Ideation is installed). */
  kinds: ProductKind[];
  onClose: () => void;
  onSaved: (result: ProductSaveResult) => void;
}

/**
 * Create/Edit a catalog product (CRUD-UX standard: modal by default). Basic
 * scalar fields map to the core `/products` contract. When `kind === 'software'`
 * a **Product domain base** field appears - the absolute origin used to mint
 * ideation idea links - wired to the ideation delivery config
 * (GET/PUT /ideation/products/{id}/delivery). It is saved AFTER the product on
 * create (needs the new id) and only when it changed on edit. Every section is
 * always rendered; the software section shows a helper note.
 *
 * With the Foundryx UIUX switch on the same form and save render as
 * `FxProductFormDialog`; with it off this is today's dialog, unchanged
 * (pinned by `__parity__/products.parity.test.tsx`).
 */
export function ProductFormDialog(props: ProductFormDialogProps) {
  return useFx() ? <FxProductFormDialog {...props} /> : <ProductFormDialogLegacy {...props} />;
}

function ProductFormDialogLegacy({ product, kinds, onClose, onSaved }: ProductFormDialogProps) {
  const {
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
    handleSave: save,
  } = useProductForm(product, kinds);

  const handleSave = () => save(onSaved, onClose);

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
