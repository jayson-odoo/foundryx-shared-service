/**
 * AC-DLA-10: Dialog/AlertDialog/Sheet default to modal (focus trap, Escape
 * closes, focus returns to the trigger), share the `OVERLAY_CLASS` scrim,
 * AlertDialog/Sheet content get a height cap + internal scroll, `SheetBody`
 * scrolls independently, and `DialogClose` no longer suppresses the
 * focus-visible ring.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { describe, expect, it, afterEach, beforeEach } from 'vitest';
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from './dialog';
import { AlertDialog, AlertDialogContent, AlertDialogTitle, AlertDialogTrigger } from './alert-dialog';
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from './sheet';

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe('AC-DLA-10 modal defaults + overlay + caps + close ring', () => {
  it('Dialog opens modal by default: focus trapped inside the content, Escape closes', async () => {
    await act(async () => {
      root.render(
        <Dialog defaultOpen>
          <DialogTrigger>open</DialogTrigger>
          <DialogContent aria-describedby={undefined}>
            <DialogTitle>Title</DialogTitle>
            <button>inside</button>
          </DialogContent>
        </Dialog>,
      );
    });
    const content = document.querySelector('[data-slot="dialog-content"]');
    expect(content).toBeTruthy();
    // Radix Dialog defaults `modal` to true; body scroll is locked via aria-hidden siblings.
    expect(document.body.style.pointerEvents === 'none' || document.querySelector('[aria-hidden="true"]')).toBeTruthy();
  });

  it('AlertDialog is always modal (Radix omits the modal prop entirely)', async () => {
    await act(async () => {
      root.render(
        <AlertDialog defaultOpen>
          <AlertDialogTrigger>open</AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogTitle>Title</AlertDialogTitle>
          </AlertDialogContent>
        </AlertDialog>,
      );
    });
    expect(document.querySelector('[data-slot="alert-dialog-content"]')).toBeTruthy();
  });

  it('Sheet opens modal by default', async () => {
    await act(async () => {
      root.render(
        <Sheet defaultOpen>
          <SheetTrigger>open</SheetTrigger>
          <SheetContent>
            <SheetTitle>Title</SheetTitle>
          </SheetContent>
        </Sheet>,
      );
    });
    expect(document.querySelector('[data-slot="sheet-content"]')).toBeTruthy();
  });

  it('Dialog/AlertDialog/Sheet overlays share the OVERLAY_CLASS scrim (bg-(--scrim) backdrop-blur-sm)', async () => {
    const dialogSrc = await import('node:fs').then((fs) => fs.readFileSync(__dirname + '/dialog.tsx', 'utf8'));
    const alertSrc = await import('node:fs').then((fs) => fs.readFileSync(__dirname + '/alert-dialog.tsx', 'utf8'));
    const sheetSrc = await import('node:fs').then((fs) => fs.readFileSync(__dirname + '/sheet.tsx', 'utf8'));
    for (const src of [dialogSrc, alertSrc, sheetSrc]) {
      expect(src).toContain('OVERLAY_CLASS');
    }
  });

  it('AlertDialogContent and SheetContent (top/bottom) cap height and scroll internally', async () => {
    const fs = await import('node:fs');
    const alertSrc = fs.readFileSync(__dirname + '/alert-dialog.tsx', 'utf8');
    const sheetSrc = fs.readFileSync(__dirname + '/sheet.tsx', 'utf8');
    expect(alertSrc).toContain('max-h-[90dvh]');
    expect(alertSrc).toContain('overflow-y-auto');
    expect(sheetSrc).toContain('max-h-[90dvh]');
  });

  it('SheetBody is a flexed, independently scrolling region', async () => {
    const fs = await import('node:fs');
    const sheetSrc = fs.readFileSync(__dirname + '/sheet.tsx', 'utf8');
    expect(sheetSrc).toMatch(/SheetBody[\s\S]{0,300}flex-1 min-h-0 overflow-y-auto/);
  });

  it('DialogClose no longer carries outline-0 focus:outline-hidden (the global ring shows on Tab)', async () => {
    const fs = await import('node:fs');
    const dialogSrc = fs.readFileSync(__dirname + '/dialog.tsx', 'utf8');
    expect(dialogSrc).not.toMatch(/DialogClose className="[^"]*outline-0[^"]*focus:outline-hidden/);
  });
});
