import Link from 'next/link';
import { toAbsoluteUrl } from '@/lib/helpers';
import { cn } from '@/lib/utils';

export interface AuthBrandPanelProps {
  /** Tagline shown under the logo. Empty/null = none (branded tenants, plan 03). */
  tagline?: string | null;
  /**
   * Wordmark logo: /public path or full/data URL. `undefined` = FoundryX default;
   * `null` = no logo — the panel shows `brandName` instead (a branded tenant
   * must NEVER fall back to the FoundryX wordmark — white-label rule).
   */
  logoSrc?: string | null;
  /** Text wordmark rendered when `logoSrc` is null (the tenant's name). */
  brandName?: string | null;
  /** Illustration path/URL. null = hidden (branded tenants without one). */
  illustrationSrc?: string | null;
  className?: string;
}

/** /public paths go through toAbsoluteUrl; full/data URLs pass untouched. */
const resolveSrc = (src: string): string =>
  src.startsWith('/') ? toAbsoluteUrl(src) : src;

/**
 * Brand panel — the solid-primary left side of auth screens. FoundryX by
 * default; tenant branding (sprint-2/03) feeds logo/tagline/illustration via
 * props and recolors the panel through the `bg-primary` token.
 * Hidden below `lg` (the form takes the full width on small screens).
 */
export function AuthBrandPanel({
  tagline = 'One platform, every conversation.',
  logoSrc = '/media/foundryx/foundryx-logo.png',
  brandName,
  illustrationSrc = '/media/foundryx/auth-illustration.svg',
  className,
}: AuthBrandPanelProps) {
  return (
    <div
      className={cn(
        'relative hidden flex-col overflow-hidden bg-primary lg:flex',
        className,
      )}
    >
      <div className="flex flex-col gap-5 p-10 lg:p-16">
        <Link href="/" className="inline-flex">
          {logoSrc ? (
            <img
              src={resolveSrc(logoSrc)}
              className="h-10 w-auto max-w-none"
              alt="Logo"
            />
          ) : (
            brandName && (
              <span className="font-heading text-4xl font-bold text-primary-foreground">
                {brandName}
              </span>
            )
          )}
        </Link>
        {tagline && (
          <p className="font-heading text-2xl font-semibold text-primary-foreground">
            {tagline}
          </p>
        )}
      </div>

      {illustrationSrc && (
        <img
          src={resolveSrc(illustrationSrc)}
          className="mt-auto w-full max-w-[560px] self-center px-10 pb-6"
          alt=""
          aria-hidden="true"
        />
      )}
    </div>
  );
}
