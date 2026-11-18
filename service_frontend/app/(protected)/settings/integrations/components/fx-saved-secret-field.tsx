'use client';

/**
 * A saved connection's secret while editing, with the Foundryx UIUX switch on
 * (gap audit 11, "Typing one in ... A saved one comes back as Saved with
 * Replace, never filled in"). The API never returns a secret or its last
 * characters, so it reads "Saved" alone (as the embed secret does).
 * - Replace opens an empty password field (with its eye) for the new value.
 * - Keep saved closes it again and empties it, so nothing travels.
 * The request is the legacy look's: an empty field is left out of the save,
 * which keeps the stored secret (`toConnectionInput`).
 */
import { useState, type Ref } from 'react';
import { Button } from '@/components/ui/button';
import { SecretInput } from '@/components/platform/secret-input';
import { FX_FIELD_BOX } from '@/components/fx/fields/classes';
import { cn } from '@/lib/utils';
import type { ProviderField } from '@/types/integration';

/** What a saved secret reads as: "Saved" for a required one (it is always
 *  set), "Not shown" for an optional one (the API cannot say whether it is). */
export function fxSavedSecretWord(f: ProviderField): string {
  return f.required ? 'Saved' : 'Not shown';
}

export function FxSavedSecretField({
  field: f,
  value,
  onChange,
  onBlur,
  name,
  inputRef,
}: {
  field: ProviderField;
  value: string;
  onChange: (value: string) => void;
  onBlur: () => void;
  name: string;
  inputRef: Ref<HTMLInputElement>;
}) {
  const [replacing, setReplacing] = useState(value !== '');

  if (!replacing) {
    return (
      <div
        data-fx-saved-secret={f.key}
        className={cn(FX_FIELD_BOX, 'h-8.5 justify-between gap-2 ps-3 pe-1 text-[0.8125rem]')}
      >
        <span className="text-(--fx-ink-2)">{fxSavedSecretWord(f)}</span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label={`Replace ${f.label}`}
          onClick={() => setReplacing(true)}
        >
          Replace
        </Button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <div className="min-w-0 flex-1">
        <SecretInput
          ref={inputRef}
          name={name}
          aria-label={f.label}
          placeholder={f.placeholder}
          autoComplete="new-password"
          autoFocus
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onBlur}
        />
      </div>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="shrink-0"
        onClick={() => {
          onChange('');
          setReplacing(false);
        }}
      >
        Keep saved
      </Button>
    </div>
  );
}
