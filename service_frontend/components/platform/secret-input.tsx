'use client';

import { forwardRef, useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export type SecretInputProps = Omit<React.ComponentProps<typeof Input>, 'type'>;

/**
 * Password-style input with the mandatory reveal toggle (user mandate — every
 * secret input gets an eye). Extracted from the integration wizard when the
 * wizard retired (plan 06 D6).
 */
export const SecretInput = forwardRef<HTMLInputElement, SecretInputProps>(
  function SecretInput(props, ref) {
    const [revealed, setRevealed] = useState(false);
    return (
      <div className="relative">
        <Input ref={ref} type={revealed ? 'text' : 'password'} {...props} />
        <Button
          type="button"
          variant="ghost"
          mode="icon"
          size="sm"
          tabIndex={-1}
          aria-label={revealed ? 'Hide value' : 'Show value'}
          className="absolute end-1 top-1/2 -translate-y-1/2"
          onClick={() => setRevealed((s) => !s)}
        >
          {revealed ? (
            <EyeOff className="text-muted-foreground" />
          ) : (
            <Eye className="text-muted-foreground" />
          )}
        </Button>
      </div>
    );
  },
);
