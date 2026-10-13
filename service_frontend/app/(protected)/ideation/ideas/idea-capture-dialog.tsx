'use client';

import { useState } from 'react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { SearchSelect } from '@/components/platform/search-select';
import type { IdeaCreateInput } from '@/services/ideation-service';
import type { Product } from '@/types/ideation';
import { AttachmentDrop, type DroppedAttachment } from './components/attachment-drop';
import { UseCasesInput } from './components/idea-form-fields';

interface IdeaCaptureDialogProps {
  products: Product[];
  onClose: () => void;
  onCreate: (input: IdeaCreateInput) => Promise<void>;
}

/**
 * Manually capture an idea (plan Phase A). The WhatsApp path fills the same
 * fields via the `create_idea` tool; this is the in-app equivalent for typing an
 * idea directly. Product is required (an idea always targets one product); the
 * one-line problem is the headline, the raw text is the verbatim capture.
 */
export function IdeaCaptureDialog({ products, onClose, onCreate }: IdeaCaptureDialogProps) {
  const [productId, setProductId] = useState<string | null>(products[0]?.id ?? null);
  const [problem, setProblem] = useState('');
  const [title, setTitle] = useState('');
  const [desiredOutcome, setDesiredOutcome] = useState('');
  const [useCases, setUseCases] = useState<string[]>([]);
  const [currentWorkaround, setCurrentWorkaround] = useState('');
  const [rawText, setRawText] = useState('');
  const [attachments, setAttachments] = useState<DroppedAttachment[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const valid = !!productId && problem.trim().length > 0;

  const handleSave = async () => {
    if (!valid || !productId) return;
    setSaving(true);
    setError(null);
    try {
      await onCreate({
        productId,
        problem: problem.trim(),
        title: title.trim(),
        desiredOutcome: desiredOutcome.trim(),
        useCases: useCases.map((u) => u.trim()).filter(Boolean),
        currentWorkaround: currentWorkaround.trim(),
        rawText: rawText.trim(),
        attachments,
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not capture the idea.');
      setSaving(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Capture idea</DialogTitle>
          <DialogDescription>
            The rawest capture - a structured Business Requirement comes later.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label>
              Product <span className="text-destructive">*</span>
            </Label>
            <SearchSelect
              options={products.map((p) => ({ label: p.name, value: p.id }))}
              value={productId}
              onChange={setProductId}
              placeholder="Select a product…"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="idea-title">Title</Label>
            <Input
              id="idea-title"
              value={title}
              placeholder="A short name for the idea"
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="idea-problem">
              Business problem <span className="text-destructive">*</span>
            </Label>
            <Textarea
              id="idea-problem"
              value={problem}
              rows={3}
              placeholder="What problem does the business have?"
              onChange={(e) => setProblem(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="idea-desired-outcome">Desired outcome</Label>
            <Textarea
              id="idea-desired-outcome"
              value={desiredOutcome}
              rows={2}
              placeholder="What should be true once it is solved?"
              onChange={(e) => setDesiredOutcome(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Use cases</Label>
            <UseCasesInput value={useCases} onChange={setUseCases} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="idea-current-workaround">Current workaround</Label>
            <Textarea
              id="idea-current-workaround"
              value={currentWorkaround}
              rows={2}
              placeholder="How is it handled today?"
              onChange={(e) => setCurrentWorkaround(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="idea-raw">Original message</Label>
            <Textarea
              id="idea-raw"
              value={rawText}
              rows={3}
              placeholder="The message as it was sent"
              onChange={(e) => setRawText(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Attachments</Label>
            <AttachmentDrop onChange={setAttachments} />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={() => void handleSave()} disabled={!valid || saving}>
            {saving ? 'Capturing…' : 'Capture idea'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
