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
    <div
      data-testid={testId}
      className="grid min-w-0 grid-cols-[minmax(0,1fr)] overflow-hidden rounded-lg border border-border bg-muted"
    >
      <div className="flex justify-end border-b border-border px-2 py-1.5">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label={isCopied ? 'Copied' : 'Copy'}
          onClick={() => copyToClipboard(code)}
        >
          {isCopied ? <Check aria-hidden /> : <Copy aria-hidden />}
          {isCopied ? 'Copied' : 'Copy'}
        </Button>
      </div>
      <pre className="overflow-x-auto p-3 font-mono text-xs leading-relaxed text-foreground">
        <code>{code}</code>
      </pre>
    </div>
  );
}
