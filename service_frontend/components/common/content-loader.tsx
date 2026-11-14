import { cn } from '@/lib/utils';
import { Skeleton } from '@/components/ui/skeleton';

export type ContentLoaderVariant = 'block' | 'card' | 'inline';

export interface ContentLoaderProps {
  /**
   * `block` (default) - a filled rectangle standing in for a chunk of
   * content (drop-in for a spinner+text placeholder that used to fill a
   * grown container). `card` - a few text-line bars, for a card-shaped
   * region. `inline` - one short bar, for a small in-line spot.
   */
  variant?: ContentLoaderVariant;
  className?: string;
}

/**
 * Generic ad-hoc content placeholder (AC-DLA-49) - a `Skeleton` shape, not
 * a spinner+text pill (the bare "loading" word is banned repo-wide as UI
 * copy; a skeleton holds the space and communicates "content is arriving"
 * without narrating it).
 */
export function ContentLoader({ variant = 'block', className }: ContentLoaderProps) {
  if (variant === 'inline') {
    return <Skeleton className={cn('h-4 w-24', className)} />;
  }

  if (variant === 'card') {
    return (
      <div className={cn('flex w-full flex-col gap-2', className)}>
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-3.5 w-full" />
        <Skeleton className="h-3.5 w-5/6" />
      </div>
    );
  }

  return <Skeleton className={cn('h-24 w-full grow', className)} />;
}
