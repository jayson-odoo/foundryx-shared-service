'use client';

/**
 * Password strength under a new password (playbook 0.71.0 "Password
 * strength"): four bars fill and recolour together as it gets longer and more
 * mixed: Weak (red), Fair (amber), Good (blue), Strong (mint), with the one
 * thing still missing beside the label. For the account page's new-password
 * field (page wave W4-ACCOUNT); pair it with `FxSecretInput` for the eye.
 */
import { cn } from '@/lib/utils';
import { passwordStrength } from '@/lib/fx/fields';

const FILL = ['bg-(--fx-act)', 'bg-(--fx-warn)', 'bg-(--fx-link)', 'bg-(--fx-ok)'];
const INK = ['text-(--fx-act)', 'text-(--fx-warn-ink)', 'text-(--fx-link)', 'text-(--fx-ok-ink)'];

export function FxPasswordStrength({ password, className }: { password: string; className?: string }) {
  if (!password) return null;
  const { level, label, missing } = passwordStrength(password);
  return (
    <div className={cn('flex flex-col gap-1', className)} data-fx-strength={label}>
      <div className="grid grid-cols-4 gap-1" aria-hidden="true">
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className={cn(
              'h-1 rounded-(--fx-r-pill) transition-[background-color] duration-(--fx-t-hover)',
              i <= level ? FILL[level] : 'bg-(--fx-line)',
            )}
          />
        ))}
      </div>
      <p className="text-xs" aria-live="polite">
        <span className={cn('font-semibold', INK[level])}>{label}</span>
        {missing && <span className="text-(--fx-ink-2)"> · {missing}</span>}
      </p>
    </div>
  );
}
