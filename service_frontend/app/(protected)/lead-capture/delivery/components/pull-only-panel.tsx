'use client';

import { Check, Copy } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard';

export interface PullOnlyPanelProps {
  address: string;
}

/** Pull only: the leads address the product reads with its key. */
export function PullOnlyPanel({ address }: PullOnlyPanelProps) {
  const { isCopied, copyToClipboard } = useCopyToClipboard();
  return (
    <Card>
      <CardContent className="flex flex-col gap-2 py-5">
        <Label htmlFor="lead-pull-address">Leads address</Label>
        <div className="flex items-center gap-2">
          <Input
            id="lead-pull-address"
            readOnly
            value={address}
            className="font-mono text-sm"
            onFocus={(e) => e.currentTarget.select()}
          />
          <Button
            variant="outline"
            mode="icon"
            onClick={() => copyToClipboard(address)}
            aria-label="Copy leads address"
          >
            {isCopied ? <Check className="size-4 text-success" /> : <Copy className="size-4" />}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
