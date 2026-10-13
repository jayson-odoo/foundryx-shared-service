'use client';

import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { useIdeaPortal, usePortalProducts, usePortalSubmit } from '@/hooks/use-idea-portal';
import { SearchSelect } from '@/components/platform/search-select';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

function Field({ id, label, required, children }: { id: string; label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>
        {label}
        {required && <span className="text-primary"> *</span>}
      </Label>
      {children}
    </div>
  );
}

/** Feedback tab: submit an idea with the owner-ruled fields. */
export function SubmitIdeaForm() {
  const router = useRouter();
  const { paths, principal } = useIdeaPortal();
  const products = usePortalProducts();
  const { submit, submitting, error } = usePortalSubmit();
  const [title, setTitle] = useState('');
  const [problem, setProblem] = useState('');
  const [desiredOutcome, setDesiredOutcome] = useState('');
  const [useCases, setUseCases] = useState('');
  const [currentWorkaround, setCurrentWorkaround] = useState('');
  const [productId, setProductId] = useState<string | null>(null);

  const list = products.data ?? [];
  const effectiveProduct = principal.productId ?? productId ?? (list.length === 1 ? list[0].id : null);
  const canSubmit = Boolean(title.trim() && problem.trim() && effectiveProduct) && !submitting;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    const created = await submit({
      title: title.trim(),
      problem: problem.trim(),
      productId: effectiveProduct,
      desiredOutcome: desiredOutcome.trim() || null,
      useCases: useCases
        .split(/\r?\n/)
        .map((l) => l.trim())
        .filter(Boolean),
      currentWorkaround: currentWorkaround.trim() || null,
    });
    if (created) router.push(paths.idea(created.id));
  };

  return (
    <Card id="submit" data-testid="portal-submit">
      <CardContent className="py-4">
        <form className="flex flex-col gap-3" onSubmit={onSubmit}>
          <h2 className="font-heading font-semibold">Submit an idea</h2>
          <Field id="portal-title" label="Title" required>
            <Input id="portal-title" value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field id="portal-problem" label="Business problem" required>
            <Textarea id="portal-problem" rows={3} value={problem} maxLength={4000} onChange={(e) => setProblem(e.target.value)} />
          </Field>
          <Field id="portal-outcome" label="Desired outcome">
            <Textarea id="portal-outcome" rows={2} value={desiredOutcome} maxLength={4000} onChange={(e) => setDesiredOutcome(e.target.value)} />
          </Field>
          <Field id="portal-usecases" label="Use cases">
            <Textarea id="portal-usecases" rows={2} value={useCases} maxLength={4000} onChange={(e) => setUseCases(e.target.value)} />
          </Field>
          <Field id="portal-workaround" label="Current workaround">
            <Textarea id="portal-workaround" rows={2} value={currentWorkaround} maxLength={4000} onChange={(e) => setCurrentWorkaround(e.target.value)} />
          </Field>
          {!principal.productId && list.length > 1 && (
            <Field id="portal-product" label="Product" required>
              <SearchSelect
                ariaLabel="Product"
                options={list.map((p) => ({ value: p.id, label: p.name }))}
                value={productId}
                onChange={setProductId}
              />
            </Field>
          )}
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" disabled={!canSubmit}>
            {submitting ? 'Submitting…' : 'Submit'}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
