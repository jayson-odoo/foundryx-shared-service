/**
 * Products under the Foundryx UIUX switch (slice W1-PRODUCTS): the pure
 * words and values the page and its dialog use with the switch on.
 */
import { CURRENCY_CODES, formatMoneyFx } from '@/lib/money';
import type { Product, ProductUpdateInput } from '@/services/productService';

/**
 * The dialog's red action in full, following what is typed:
 * "Add Barcode scanner at RM 189.00", "Save Cloud hosting at USD 1,200.50",
 * or the short label while there is no name yet.
 */
export function fxProductActionLabel(input: {
  isEdit: boolean;
  name: string;
  price: number | null;
  currency: string | null | undefined;
}): string {
  const name = input.name.trim();
  if (!name) return input.isEdit ? 'Save changes' : 'Add product';
  const verb = input.isEdit ? 'Save' : 'Add';
  return input.price === null
    ? `${verb} ${name}`
    : `${verb} ${name} at ${formatMoneyFx(input.price, input.currency || null)}`;
}

/** The currencies to pick from: the common list, plus the product's own
 *  code when it is not on it, so an edit never loses it. */
export function fxCurrencyCodes(current: string | null | undefined): string[] {
  const code = (current ?? '').trim().toUpperCase();
  return code && !CURRENCY_CODES.includes(code) ? [code, ...CURRENCY_CODES] : [...CURRENCY_CODES];
}

/** The fields an Undo of an edit writes back: the product as it was. */
export function productRestorePayload(before: Product): ProductUpdateInput {
  return {
    name: before.name,
    kind: before.kind,
    sku: before.sku,
    defaultPrice: before.defaultPrice,
    tax: before.tax,
    currency: before.currency,
    uom: before.uom,
    isActive: before.isActive,
  };
}

/** Tax % steps by whole points; a rate already holding decimals keeps them. */
export function fxTaxStep(value: number): number {
  return Number.isInteger(value) ? 1 : 0.01;
}

/** The decimals a tax rate holds: the API stores it as Numeric(14, 4), so
 *  the stepper shows, steps and sends it at 4 places at most and a stored
 *  value with binary residue still reads as its rate. */
export const FX_TAX_PRECISION = 4;

export const FX_TAX_MIN = 0;
export const FX_TAX_MAX = 100;
