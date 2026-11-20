/**
 * One page-level browser-tab title that wins over the host tenant's name
 * (lane SS-MULTI-PRODUCT-BOARD: a product's feedback board reads
 * "<product> feedback" even on a branded host). `BrandingProvider` re-asserts
 * its title through a MutationObserver; it reads this override first, so two
 * writers never fight over `document.title`.
 */
let override: string | null = null;

export function setPageTitleOverride(title: string | null): void {
  override = title;
}

export function getPageTitleOverride(): string | null {
  return override;
}
