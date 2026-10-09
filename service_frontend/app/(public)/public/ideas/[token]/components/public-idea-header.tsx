/**
 * Issue #90 W1 (AC-90-110) - the public idea page's own header (the shell's
 * chrome is opted out for `/public/ideas/`, see `ownsChromePath`). On-brand
 * bar (border + heading type) showing the idea's core PRODUCT name (R1: the
 * idea's Product, e.g. "Sorento CRM" - never the tenant/app name). The
 * white-label mark itself lives ONLY in the footer (`PublicIdeaFooter`,
 * Q2 ruling) - a header copy would duplicate the SAME image/text node the
 * footer already carries.
 */
export interface PublicIdeaHeaderProps {
  productName: string | null;
}

export function PublicIdeaHeader({ productName }: PublicIdeaHeaderProps) {
  return (
    <header className="border-b border-border">
      <div className="mx-auto flex w-full max-w-5xl items-center px-4 py-4 sm:px-6">
        {productName && (
          <span className="font-heading text-sm font-semibold text-foreground">
            {productName}
          </span>
        )}
      </div>
    </header>
  );
}
