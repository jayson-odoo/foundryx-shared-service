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
  const [proposedSolution, setProposedSolution] = useState('');
  const [impact, setImpact] = useState('');
  const [department, setDepartment] = useState('');
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
        proposedSolution: proposedSolution.trim(),
        impact: impact.trim(),
        department: department.trim(),
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
            The rawest capture — a structured Business Requirement comes later.
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
            <Label htmlFor="idea-problem">
              Problem statement <span className="text-destructive">*</span>
            </Label>
            <Textarea
              id="idea-problem"
              value={problem}
              rows={3}
              placeholder="What's the problem or observation? e.g. CS can't export orders to Excel"
              onChange={(e) => setProblem(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="idea-proposed-solution">Proposed solution</Label>
            <Textarea
              id="idea-proposed-solution"
              value={proposedSolution}
              rows={3}
              placeholder="How could we solve it? e.g. Add an Export to Excel button on the orders list"
              onChange={(e) => setProposedSolution(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="idea-impact">Impact</Label>
            <Textarea
              id="idea-impact"
              value={impact}
              rows={3}
              placeholder="What does it improve? e.g. Saves CS 30 minutes a day"
              onChange={(e) => setImpact(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="idea-department">Department</Label>
            <Input
              id="idea-department"
              value={department}
              placeholder="Which team is this for? e.g. Customer Service"
              onChange={(e) => setDepartment(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="idea-raw">Raw notes</Label>
            <Textarea
              id="idea-raw"
              value={rawText}
              rows={3}
              placeholder="Verbatim context — paste the message, or add detail."
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
