/**
 * Canvas-editor sub-component tests (palette + inspector). The Konva Stage is
 * exercised in the live Playwright E2E (jsdom has no canvas); here we verify the
 * click-to-add palette and the inspector's geometry/unit + binding wiring.
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { CanvasPalette } from './palette';
import { CanvasInspector } from './inspector';
import { createCanvasElement, DEFAULT_BADGE_SIZE } from '@/lib/canvas-doc';
import type { CanvasTextElement } from '@/types/templates';

describe('CanvasPalette', () => {
  it('click-to-add fires for each element type (grouped, searchable)', () => {
    const onAdd = vi.fn();
    render(<CanvasPalette onAdd={onAdd} />);
    const search = screen.getByPlaceholderText('Search elements');
    const byLabel: Array<[string, string]> = [
      ['text', 'Text'],
      ['image', 'Image'],
      ['qr', 'QR'],
      ['shape', 'Shape'],
      ['divider', 'Divider'],
      ['socialLinks', 'Social'],
      ['brandHeader', 'Brand header'],
      ['brandFooter', 'Brand footer'],
      ['customHtml', 'Custom HTML'],
    ];
    for (const [type, label] of byLabel) {
      // Search auto-expands the matching category.
      fireEvent.change(search, { target: { value: label } });
      fireEvent.click(screen.getByTestId(`palette-add-${type}`));
      expect(onAdd).toHaveBeenCalledWith(type);
    }
  });
});

describe('CanvasInspector', () => {
  const text = createCanvasElement('text', DEFAULT_BADGE_SIZE) as CanvasTextElement;

  it('shows a placeholder when nothing is selected', () => {
    render(
      <CanvasInspector
        element={null}
        unit="mm"
        mergeFields={[]}
        visibilityFacts={[]}
        onChange={vi.fn()}
        onReorder={vi.fn()}
        onRemove={vi.fn()}
      />,
    );
    expect(screen.getByText(/select an element/i)).toBeInTheDocument();
  });

  it('edits geometry in mm', () => {
    const onChange = vi.fn();
    render(
      <CanvasInspector
        element={text}
        unit="mm"
        mergeFields={[{ key: 'attendeeName', label: 'Name', sample: 'Alex' }]}
        visibilityFacts={[]}
        onChange={onChange}
        onReorder={vi.fn()}
        onRemove={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText('X (mm)'), { target: { value: '20' } });
    expect(onChange).toHaveBeenCalledWith({ x: 20 });
  });

  it('converts inches → mm on geometry edit', () => {
    const onChange = vi.fn();
    render(
      <CanvasInspector
        element={text}
        unit="in"
        mergeFields={[]}
        visibilityFacts={[]}
        onChange={onChange}
        onReorder={vi.fn()}
        onRemove={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText('W (in)'), { target: { value: '1' } });
    // 1in = 25.4mm
    expect(onChange).toHaveBeenCalledWith({ w: 25.4 });
  });

  it('reorder + delete callbacks fire', () => {
    const onReorder = vi.fn();
    const onRemove = vi.fn();
    render(
      <CanvasInspector
        element={text}
        unit="mm"
        mergeFields={[]}
        visibilityFacts={[]}
        onChange={vi.fn()}
        onReorder={onReorder}
        onRemove={onRemove}
      />,
    );
    fireEvent.click(screen.getByLabelText('Bring forward'));
    expect(onReorder).toHaveBeenCalledWith(1);
    fireEvent.click(screen.getByRole('button', { name: /delete element/i }));
    expect(onRemove).toHaveBeenCalled();
  });
});
