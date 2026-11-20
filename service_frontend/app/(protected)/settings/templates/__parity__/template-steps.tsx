/**
 * One set of editing actions on a template record, run the same way in both
 * looks (Foundryx UIUX, slice W4-TEMPLATES): pick the text block, type into
 * the rich text field, use the toolbar (Bold, Italic, a bulleted list, a link),
 * insert a merge field, add a heading block's text, then change the name and
 * subject on the Settings tab and save.
 *
 * jsdom has no editing commands, so a test installs a stand-in
 * `document.execCommand` (`fakeExecCommand`) that changes the focused field's
 * markup the same way every time; what the editor then commits is what the
 * page saves.
 */
import { act, fireEvent, screen } from '@testing-library/react';
import { vi } from 'vitest';
import { settle } from './template-test-kit';

/** A repeatable stand-in for the browser's editing commands. */
export function fakeExecCommand(command: string, _ui?: boolean, arg?: string): boolean {
  const el = document.activeElement as HTMLElement | null;
  if (!el || el.getAttribute('contenteditable') !== 'true') return false;
  const tags: Record<string, string> = {
    bold: 'b',
    italic: 'i',
    underline: 'u',
    insertUnorderedList: 'ul',
    insertOrderedList: 'ol',
  };
  if (command === 'insertText') el.innerHTML += arg ?? '';
  else if (command === 'createLink') el.innerHTML += `<a href="${arg}">link</a>`;
  else if (tags[command]) {
    const t = tags[command];
    el.innerHTML += t === 'ul' || t === 'ol' ? `<${t}><li>item</li></${t}>` : `<${t}>${command}</${t}>`;
  }
  return true;
}

/** Picks a Radix tab by its name. */
export async function openTab(name: string): Promise<void> {
  const tab = screen.getByRole('tab', { name });
  fireEvent.mouseDown(tab, { button: 0 });
  fireEvent.click(tab);
  await settle();
}

/** Opens the record's gear menu (switch off) and runs one of its items. */
export async function openGearItem(name: RegExp): Promise<void> {
  const triggers = screen.getAllByRole('button', { name: /actions|more|settings/i });
  fireEvent.pointerDown(triggers[triggers.length - 1], { button: 0 });
  await settle();
  fireEvent.click(await screen.findByRole('menuitem', { name }));
  await settle();
}

/**
 * The editing actions. `snapshot(label)` is called at the points where the
 * caller wants the screen recorded (switch-off parity only).
 */
export async function editTemplateRecord(
  container: Element,
  snapshot?: (label: string) => void,
): Promise<void> {
  const prompt = vi.spyOn(window, 'prompt').mockReturnValue('https://maju.my/start');

  // The text block, edited through the rich text field.
  fireEvent.click(container.querySelector('[data-testid="canvas-block-blk_text"]') as Element);
  await settle();
  snapshot?.('text block selected');
  const box = screen.getByTestId('rich-text-editable');
  act(() => box.focus());
  box.innerHTML = 'Your account is <b>ready</b>. Sign in today.';
  fireEvent.input(box);
  for (const label of ['Bold', 'Italic', 'Bulleted list']) {
    fireEvent.mouseDown(screen.getByRole('button', { name: label }), { button: 0 });
  }
  fireEvent.mouseDown(screen.getByRole('button', { name: 'Insert link' }), { button: 0 });
  fireEvent.mouseDown(screen.getByTestId('merge-chip-recipient.firstName'), { button: 0 });
  fireEvent.blur(box);
  await settle();

  // The heading block's text.
  fireEvent.click(container.querySelector('[data-testid="canvas-block-blk_head"]') as Element);
  await settle();
  fireEvent.change(screen.getByLabelText('Heading text'), { target: { value: 'Hello {{recipient.firstName}}' } });
  await settle();

  // Name and subject on the Settings tab.
  await openTab('Settings');
  fireEvent.change(screen.getByLabelText('Template name'), { target: { value: 'Welcome email v2' } });
  fireEvent.change(screen.getByLabelText('Subject'), { target: { value: 'Welcome aboard, {{recipient.firstName}}' } });
  await settle();

  fireEvent.click(screen.getByRole('button', { name: /^Save/ }));
  await settle();
  prompt.mockRestore();
}

/** The new template form: add a text block's words, name, subject, context, Create. */
export async function createTemplate(): Promise<void> {
  await openTab('Settings');
  fireEvent.change(screen.getByLabelText('Template name'), { target: { value: 'Order shipped' } });
  fireEvent.change(screen.getByLabelText('Subject'), { target: { value: 'Your order is on its way' } });
  const context = screen.getByRole('combobox', { name: 'Template context' });
  fireEvent.click(context);
  await settle();
  fireEvent.click(await screen.findByRole('option', { name: /User account/ }));
  await settle();
  fireEvent.click(screen.getByRole('button', { name: /^Create|^Save/ }));
  await settle();
}
