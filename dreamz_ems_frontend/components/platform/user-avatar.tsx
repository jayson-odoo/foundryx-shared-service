import { cn } from '@/lib/utils';
import { initials } from '@/lib/format';
import type { User } from '@/types/user';

// Deterministic palette pick from the name so a user's colour is stable.
const PALETTE = [
  'bg-blue-500',
  'bg-emerald-500',
  'bg-violet-500',
  'bg-amber-500',
  'bg-rose-500',
  'bg-cyan-500',
  'bg-indigo-500',
  'bg-orange-500',
];

function colorFor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) hash = (hash * 31 + seed.charCodeAt(i)) | 0;
  return PALETTE[Math.abs(hash) % PALETTE.length];
}

const SIZES = {
  sm: 'size-8 text-xs',
  md: 'size-9 text-sm',
  lg: 'size-12 text-base',
} as const;

export interface UserAvatarProps {
  user: Pick<User, 'name' | 'email' | 'avatar'>;
  size?: keyof typeof SIZES;
  className?: string;
}

/** Initials avatar (colored), image if present. Shared platform piece since plan 06 (header, account, users). */
export function UserAvatar({ user, size = 'md', className }: UserAvatarProps) {
  const seed = user.name ?? user.email;

  if (user.avatar) {
    return (
      <img
        src={user.avatar}
        alt={user.name ?? user.email}
        className={cn('rounded-full object-cover', SIZES[size], className)}
      />
    );
  }

  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white',
        SIZES[size],
        colorFor(seed),
        className,
      )}
    >
      {initials(user.name)}
    </span>
  );
}
