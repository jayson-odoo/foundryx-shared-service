import Link from 'next/link';
import { cn } from '@/lib/utils';

export interface AuthFooterLink {
  label: string;
  href: string;
}

export interface AuthFooterProps {
  links?: AuthFooterLink[];
  className?: string;
}

const DEFAULT_LINKS: AuthFooterLink[] = [
  { label: 'Terms', href: '#' },
  { label: 'Plans', href: '#' },
  { label: 'Contact Us', href: '#' },
];

/**
 * Auth footer - secondary navigation shown on auth pages.
 * Links are stubbed (`href="#"`) until the corresponding pages ship (see BL-003).
 */
export function AuthFooter({ links = DEFAULT_LINKS, className }: AuthFooterProps) {
  return (
    <nav className={cn('flex items-center justify-center gap-6', className)}>
      {links.map((link) => (
        <Link
          key={link.label}
          href={link.href}
          className="font-heading text-sm font-semibold text-primary transition-colors hover:text-primary-active"
        >
          {link.label}
        </Link>
      ))}
    </nav>
  );
}
