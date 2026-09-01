/** Repro: typing then clicking the canvas text box must NOT reset content. */
import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { TemplateDocument } from '@/types/templates';
import { createBlankDocument, createBlock, insertBlock, findBlock } from '@/lib/template-doc';
import { EmailEditor } from './email-editor';

function setup() {
  let doc = createBlankDocument();
  const heading = createBlock('heading');
  if (heading.type === 'heading') heading.text = 'Welcome!';
  doc = insertBlock(doc, doc.sections[1].id, doc.sections[1].columns[0].id, heading);

  const docs: TemplateDocument[] = [];
  function Harness() {
    const [d, setD] = useState(doc);
    return (
      <EmailEditor
        doc={d}
        onChange={(next) => {
          docs.push(next);
          setD(next);
        }}
        editing
        mergeFields={[{ key: 'recipient.firstName', label: 'First name', sample: 'Alex' }]}
        visibilityFacts={[]}
        renderPreview={vi.fn()}
      />
    );
  }
  render(<Harness />);
  return { headingId: heading.id, docs, latest: () => docs.at(-1) };
}

describe('inline edit stability', () => {
  it('panel edit then canvas click+blur keeps the text', () => {
    const { headingId, latest } = setup();
    // Select the heading → panel opens.
    fireEvent.click(screen.getByTestId(`canvas-block-${headingId}`));
    const panelInput = screen.getByLabelText('Heading text');
    fireEvent.change(panelInput, { target: { value: 'Hello there' } });
    expect(
      (() => {
        const f = findBlock(latest()!, headingId)!.block;
        return f.type === 'heading' ? f.text : '';
      })(),
    ).toBe('Hello there');

    // Canvas box should now show the typed text.
    const box = screen.getByTestId(`block-heading-${headingId}`);
    expect(box.textContent).toBe('Hello there');

    // Click into the canvas box, then blur without typing - text must survive.
    fireEvent.focus(box);
    fireEvent.click(box);
    fireEvent.blur(box);
    const f = findBlock(latest()!, headingId)!.block;
    expect(f.type === 'heading' ? f.text : '').toBe('Hello there');
    expect(box.textContent).toBe('Hello there');
  });

  it('canvas typing commits on blur and survives reselection', () => {
    const { headingId, latest } = setup();
    const box = screen.getByTestId(`block-heading-${headingId}`);
    fireEvent.focus(box);
    box.textContent = 'Typed in canvas';
    fireEvent.blur(box);
    let f = findBlock(latest()!, headingId)!.block;
    expect(f.type === 'heading' ? f.text : '').toBe('Typed in canvas');

    fireEvent.click(box);
    fireEvent.blur(box);
    f = findBlock(latest()!, headingId)!.block;
    expect(f.type === 'heading' ? f.text : '').toBe('Typed in canvas');
  });
});
