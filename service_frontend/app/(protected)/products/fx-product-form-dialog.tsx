'use client';

/**
 * The product dialog with the Foundryx UIUX switch on (slice W1-PRODUCTS,
 * the approved Products mock). Same fields, same order and the same save as
 * the dialog with the switch off (`useProductForm`); what changes is how it
 * looks and reads:
 * - Default price is a money field: the currency sits inside ("RM" for MYR,
 *   the ISO code for any other), the amount is right-aligned and tidied to
 *   "1,200.00" when you leave it, never browser arrows.
 * - Currency is a searchable list instead of free text.
 * - Tax % is a stepper with round - and + either side.
 * - The red action follows what is typed ("Add Barcode scanner at RM 189.00")
 *   and, with no name yet, is greyed with its reason under it. It is the one
 *   red action while the dialog is open, so the page's hides meanwhile.
 */
import { cn } from '@/lib/utils';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { SearchSelect } from '@/components/platform/search-select';
import { FxMainAction } from '@/components/fx/actions/main-action';
import { useHideMainAction } from '@/components/fx/actions/page-actions-context';
import { FxMoneyField, FxStepper } from '@/components/fx/fields';
import type { ProductFormDialogProps } from './product-form-dialog';
import {
  FX_TAX_MAX,
  FX_TAX_MIN,
  fxCurrencyCodes,
  fxProductActionLabel,
  fxTaxStep,
} from './product-fx';
import { BOARD_COLOR_RE, toMoney, useProductForm } from './use-product-form';

const LABEL = 'text-sm font-semibold text-(--fx-ink-2)';
const FIELD = 'flex min-w-0 flex-col gap-1.5';
const NOTE = 'text-xs text-(--fx-ink-3)';
const WRONG = 'text-xs text-[color-mix(in_srgb,var(--fx-act)_82%,var(--fx-ink))]';
export const FX_PRODUCT_NAME_TARGET = 'product-name';

export function FxProductFormDialog({ product, kinds, onClose, onSaved }: ProductFormDialogProps) {
  const f = useProductForm(product, kinds);
  useHideMainAction(true);

  const price = toMoney(f.defaultPrice);
  const taxValue = toMoney(f.tax) ?? 0;
  const shortLabel = f.isEdit ? 'Save changes' : 'Add product';
  const fullLabel = fxProductActionLabel({
    isEdit: f.isEdit,
    name: f.name,
    price,
    currency: f.currency,
  });
  const deliveryOff = f.deliveryLoading || Boolean(f.deliveryError);

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        data-fx-product-dialog=""
        showCloseButton={false}
        className="max-h-[calc(100dvh-32px)] max-w-lg gap-4 overflow-y-auto rounded-(--fx-r-l) border-(--fx-line) bg-(--fx-surface) p-6 text-(--fx-ink) max-sm:w-[calc(100%-32px)] max-sm:p-4"
      >
        <div className="flex flex-col gap-1">
          <DialogTitle className="text-lg font-bold text-(--fx-ink)">
            {f.isEdit ? 'Edit product' : 'Add product'}
          </DialogTitle>
          <DialogDescription className="text-sm text-(--fx-ink-2)">
            {f.isEdit
              ? 'Update the catalog product details.'
              : 'Create a catalog product (goods, service, or software).'}
          </DialogDescription>
        </div>

        <div className={FIELD} data-fx-pulse-target={FX_PRODUCT_NAME_TARGET}>
          <label htmlFor="prod-name" className={LABEL}>
            Name
          </label>
          <Input
            id="prod-name"
            value={f.name}
            onChange={(e) => f.setName(e.target.value)}
            placeholder="e.g. Sorento CRM"
            autoFocus
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className={FIELD}>
            <span className={LABEL}>Kind</span>
            <SearchSelect
              options={f.kindOptions}
              value={f.kind}
              onChange={f.setKind}
              placeholder="Select a kind…"
              ariaLabel="Product kind"
            />
          </div>
          <div className={FIELD}>
            <label htmlFor="prod-sku" className={LABEL}>
              SKU
            </label>
            <Input
              id="prod-sku"
              value={f.sku}
              onChange={(e) => f.setSku(e.target.value)}
              placeholder="Optional"
            />
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_auto]">
          <div className={FIELD}>
            <label htmlFor="prod-price" className={LABEL}>
              Default price
            </label>
            <FxMoneyField
              id="prod-price"
              value={price}
              currency={f.currency || null}
              onChange={(n) => f.setDefaultPrice(n === null ? '' : String(n))}
              placeholder="0.00"
            />
          </div>
          <div className={FIELD}>
            <span className={LABEL}>Currency</span>
            <SearchSelect
              options={fxCurrencyCodes(f.currency).map((code) => ({ value: code, label: code }))}
              value={f.currency || null}
              onChange={(code) => f.setCurrency(code.toUpperCase())}
              placeholder="MYR"
              ariaLabel="Currency"
            />
          </div>
          <div className={FIELD}>
            <label htmlFor="prod-tax" className={LABEL}>
              Tax %
            </label>
            <FxStepper
              id="prod-tax"
              aria-label="Tax %"
              value={taxValue}
              min={FX_TAX_MIN}
              max={FX_TAX_MAX}
              step={fxTaxStep(taxValue)}
              onChange={(n) => f.setTax(String(n))}
            />
          </div>
        </div>

        <div className={FIELD}>
          <label htmlFor="prod-uom" className={LABEL}>
            Unit of measure
          </label>
          <Input
            id="prod-uom"
            value={f.uom}
            onChange={(e) => f.setUom(e.target.value)}
            placeholder="e.g. unit, licence, kg"
          />
        </div>

        <div className="flex items-center justify-between gap-3 rounded-(--fx-r-m) border border-(--fx-line) px-3 py-2.5">
          <div className="flex flex-col">
            <label htmlFor="prod-active" className="cursor-pointer text-sm font-semibold text-(--fx-ink)">
              Active
            </label>
            <span className={NOTE}>Inactive products are hidden from selection lists.</span>
          </div>
          <Switch id="prod-active" checked={f.isActive} onCheckedChange={f.setIsActive} />
        </div>

        {f.isSoftware && (
          <div className="flex flex-col gap-1.5 rounded-(--fx-r-m) border border-dashed border-(--fx-line-2) p-3">
            <label htmlFor="prod-domain-base" className={LABEL}>
              Product domain base
            </label>
            <Input
              id="prod-domain-base"
              value={f.domainBase}
              onChange={(e) => f.setDomainBase(e.target.value)}
              placeholder="https://fe-sorento.foundryx.my"
              disabled={deliveryOff}
            />
            <p className={NOTE}>
              The absolute origin of this software product&apos;s app. Feedback
              links use it (e.g. feedback captured on WhatsApp deep-links back
              here). Set it once the app has a hosted URL.
            </p>
            <label htmlFor="prod-build-repo" className={cn(LABEL, 'pt-2')}>
              Build repository
            </label>
            <Input
              id="prod-build-repo"
              value={f.buildRepo}
              onChange={(e) => {
                f.setBuildRepo(e.target.value);
                f.setBuildRepoError(null);
              }}
              placeholder="owner/repository"
              aria-invalid={f.buildRepoError ? true : undefined}
              disabled={deliveryOff}
            />
            {f.buildRepoError && <p className={WRONG}>{f.buildRepoError}</p>}
            <label htmlFor="prod-board-color" className={cn(LABEL, 'pt-2')}>
              Board colour
            </label>
            <div className="flex items-center gap-2">
              <label
                className="relative size-9 shrink-0 cursor-pointer rounded-(--fx-r-m) border border-(--fx-line-2)"
                style={{
                  background: BOARD_COLOR_RE.test(f.boardColor.trim().toLowerCase())
                    ? f.boardColor.trim()
                    : undefined,
                }}
              >
                <input
                  type="color"
                  aria-label="Pick board colour"
                  className="absolute inset-0 size-full cursor-pointer opacity-0"
                  value={
                    BOARD_COLOR_RE.test(f.boardColor.trim().toLowerCase())
                      ? f.boardColor.trim().toLowerCase()
                      : '#000000'
                  }
                  onChange={(e) => {
                    f.setBoardColor(e.target.value);
                    f.setBoardColorError(null);
                  }}
                  disabled={deliveryOff}
                />
              </label>
              <Input
                id="prod-board-color"
                value={f.boardColor}
                onChange={(e) => {
                  f.setBoardColor(e.target.value);
                  f.setBoardColorError(null);
                }}
                placeholder="#3b82f6"
                aria-invalid={f.boardColorError ? true : undefined}
                disabled={deliveryOff}
              />
            </div>
            {f.boardColorError && <p className={WRONG}>{f.boardColorError}</p>}
            <label htmlFor="prod-board-name" className={cn(LABEL, 'pt-2')}>
              Board name
            </label>
            <Input
              id="prod-board-name"
              value={f.boardName}
              onChange={(e) => f.setBoardName(e.target.value)}
              maxLength={80}
              placeholder={f.name.trim() || undefined}
              disabled={deliveryOff}
            />
            {f.deliveryLoading && <p className={NOTE}>Loading delivery config…</p>}
            {f.deliveryError && (
              <p className={WRONG}>
                {f.deliveryError} (requires the Feedback Products: Manage permission)
              </p>
            )}
          </div>
        )}

        {f.error && <p className="text-sm text-[color-mix(in_srgb,var(--fx-act)_82%,var(--fx-ink))]">{f.error}</p>}

        <div className="mt-1 flex flex-nowrap items-start justify-end gap-2">
          <Button
            type="button"
            variant="fx-quiet"
            className="h-auto min-h-11 rounded-(--fx-r-pill) px-5"
            onClick={onClose}
            disabled={f.saving}
          >
            Cancel
          </Button>
          <FxMainAction
            label={shortLabel}
            fullLabel={fullLabel}
            working={f.saving}
            blocked={
              f.valid
                ? undefined
                : { reason: 'Enter a name.', pulseTarget: FX_PRODUCT_NAME_TARGET }
            }
            onClick={() => void f.handleSave(onSaved, onClose)}
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}
