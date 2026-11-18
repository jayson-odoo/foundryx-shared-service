'use client';

import { Check, Copy } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard';

export interface CodeSampleProps {
  code: string;
  testId: string;
}

/** A code block with one Copy button (the shared copy hook: inline check, no toast). */
export function CodeSample({ code, testId }: CodeSampleProps) {
  const { copyToClipboard, isCopied } = useCopyToClipboard();
  return (
    <div data-testid={testId} className="relative min-w-0 rounded-lg border border-border bg-muted">
      <pre className="overflow-x-auto p-3 pe-24 font-mono text-xs leading-relaxed text-foreground">
        <code>{code}</code>
      </pre>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="absolute end-2 top-2"
        aria-label={isCopied ? 'Copied' : 'Copy'}
        onClick={() => copyToClipboard(code)}
      >
        {isCopied ? <Check aria-hidden /> : <Copy aria-hidden />}
        {isCopied ? 'Copied' : 'Copy'}
      </Button>
    </div>
  );
}
