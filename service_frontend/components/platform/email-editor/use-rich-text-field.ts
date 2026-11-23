'use client';

/**
 * The rich text field's editing logic (seeding, the caret, the toolbar's
 * commands, the merge-field insert, commit on input and blur), shared by both
 * looks of `RichTextField` so the HTML they emit is the same for the same
 * editing actions (Foundryx UIUX, slice W4-TEMPLATES). Moved here unchanged
 * from `rich-text-field.tsx`.
 */
import { useEffect, useRef } from 'react';

export function exec(command: string, arg?: string) {
  // execCommand is deprecated but the only zero-dep way to get exactly our
  // email-safe tag set (b/i/u/a/ul/ol); works in every current browser.
  document.execCommand(command, false, arg);
}

export function useRichTextField(value: string, onChange: (html: string) => void) {
  const ref = useRef<HTMLDivElement>(null);
  const savedRange = useRef<Range | null>(null);

  // Seed / re-seed only when the external value diverges and we're not editing.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (el.innerHTML !== value && document.activeElement !== el) {
      el.innerHTML = value;
    }
  }, [value]);

  const commit = () => {
    const el = ref.current;
    if (el) onChange(el.innerHTML);
  };

  // Remember the caret so a chip/link click (which steals focus) can restore it.
  const rememberSelection = () => {
    const sel = window.getSelection();
    if (sel && sel.rangeCount && ref.current?.contains(sel.anchorNode)) {
      savedRange.current = sel.getRangeAt(0).cloneRange();
    }
  };

  const withCaret = (fn: () => void) => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    const sel = window.getSelection();
    if (savedRange.current && sel) {
      sel.removeAllRanges();
      sel.addRange(savedRange.current);
    }
    fn();
    commit();
  };

  const applyLink = () => {
    const url = window.prompt('Link URL', 'https://');
    if (url) withCaret(() => exec('createLink', url));
  };

  const insertToken = (key: string) => {
    withCaret(() => exec('insertText', `{{${key}}}`));
  };

  return { ref, commit, rememberSelection, withCaret, applyLink, insertToken };
}
