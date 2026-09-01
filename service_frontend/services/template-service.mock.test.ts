/**
 * Mock template service - two-tier semantics (D6/D7) the Phase-B backend
 * must mirror: fork-on-edit, required-fact save gate, system delete-block,
 * reset-to-default.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { createBlankDocument } from '@/lib/template-doc';
import type { ListQuery } from '@/types/resource';
import type { TemplateDocument } from '@/types/templates';
import { __resetMockTemplates, mockTemplateEngineService as svc } from './template-service.mock';

const QUERY: ListQuery = { page: 0, pageSize: 50 };

async function firstSystemTemplate() {
  const { data } = await svc.listTemplates(QUERY);
  const item = data.find((t) => t.key === 'auth.password_reset');
  if (!item) throw new Error('seed missing');
  const full = await svc.getTemplate(item.id);
  if (!full) throw new Error('seed missing');
  return full;
}

describe('mock template service (two-tier contract)', () => {
  beforeEach(() => {
    __resetMockTemplates();
  });

  it('seeds system templates at the Default tier', async () => {
    const { data } = await svc.listTemplates(QUERY);
    expect(data.length).toBeGreaterThanOrEqual(5);
    expect(data.every((t) => t.tier === 'default' && t.isSystem)).toBe(true);
  });

  it('first edit forks a system template to Customized (D6)', async () => {
    const tpl = await firstSystemTemplate();
    const updated = await svc.updateTemplate(tpl.id, {
      name: 'My reset mail',
      subject: tpl.subject,
      context: tpl.context,
      doc: tpl.doc,
    });
    expect(updated.tier).toBe('customized');
    expect(updated.isSystem).toBe(true); // still a system KEY - only forked
  });

  it('save rejects when a required fact is missing (D7 safety rail)', async () => {
    const tpl = await firstSystemTemplate();
    // Blank doc + subject without {{resetLink}} anywhere.
    await expect(
      svc.updateTemplate(tpl.id, {
        name: tpl.name,
        subject: 'No link here',
        context: tpl.context,
        doc: createBlankDocument(),
      }),
    ).rejects.toThrow(/resetLink/);
  });

  it('reset returns a forked system template to the platform default', async () => {
    const tpl = await firstSystemTemplate();
    await svc.updateTemplate(tpl.id, {
      name: 'Renamed',
      subject: tpl.subject,
      context: tpl.context,
      doc: tpl.doc,
    });
    const reset = await svc.resetTemplate(tpl.id);
    expect(reset.tier).toBe('default');
    expect(reset.name).toBe('Password reset');
  });

  it('system templates are delete-blocked; duplicates are custom + deletable', async () => {
    const tpl = await firstSystemTemplate();
    await expect(svc.deleteTemplate(tpl.id)).rejects.toThrow(/System/);

    const copy = await svc.duplicateTemplate(tpl.id);
    expect(copy.isSystem).toBe(false);
    expect(copy.tier).toBe('customized');
    await expect(svc.deleteTemplate(copy.id)).resolves.toBeUndefined();
  });

  it('preview renders sample facts through the doc (no unresolved required tokens)', async () => {
    const tpl = await firstSystemTemplate();
    const preview = await svc.preview(tpl.doc as TemplateDocument, tpl.context, tpl.subject);
    expect(preview.html).toContain('https://acme.foundryxems.com/change-password?token=sample');
    expect(preview.subject).toContain('Acme Events');
    expect(preview.text.length).toBeGreaterThan(0);
  });

  // --- F2 document surface --------------------------------------------------

  it('exposes a document context with list facts (F2 D6/D9)', async () => {
    const contexts = await svc.listContexts();
    const invoice = contexts.find((c) => c.key === 'document.invoice_preview');
    expect(invoice).toBeDefined();
    expect(invoice?.listFacts?.[0].key).toBe('lineItems');
    expect(invoice?.listFacts?.[0].itemFacts.map((f) => f.key)).toContain('amount');
  });

  it('seeds a starter document template bound to lineItems (F2 D9)', async () => {
    const { data } = await svc.listTemplates(QUERY);
    const item = data.find((t) => t.key === 'document.invoice');
    expect(item?.type).toBe('document');
    const full = await svc.getTemplate(item!.id);
    const docModel = full!.doc as TemplateDocument;
    expect(docModel.pageSetup?.size).toBe('A4');
    const hasTable = docModel.sections.some((s) =>
      s.columns.some((c) => c.blocks.some((b) => b.type === 'table' && b.source === 'lineItems')),
    );
    expect(hasTable).toBe(true);
  });

  it('previewDocumentPdf returns a PDF blob (F2 D7)', async () => {
    const tpl = await firstSystemTemplate();
    const blob = await svc.previewDocumentPdf({
      id: tpl.id,
      doc: tpl.doc as TemplateDocument,
      context: tpl.context,
      subject: tpl.subject,
    });
    expect(blob.type).toBe('application/pdf');
    expect(blob.size).toBeGreaterThan(0);
  });
});
