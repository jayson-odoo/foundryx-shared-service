'use client';

/**
 * How a Foundryx UIUX field gets its accessible name from the label people
 * see. `FxField` with a `label` renders that label and hands its ids down;
 * every fx control (text field, text area, date, money, stepper, the
 * searchable dropdowns) picks them up, so a labelled field never depends on
 * its placeholder for a name. Order, first that is set:
 *   1. the control's own `aria-label` / `ariaLabel`;
 *   2. its own `aria-labelledby`;
 *   3. the surrounding `FxField` label (`aria-labelledby` its id, and the
 *      control takes the field's id so `<label htmlFor>` points at it);
 *   4. an `id` a page's own `<label htmlFor>` points at;
 *   5. last resort, for the dropdowns only: the placeholder.
 * One control per labelled `FxField`; a composite control (money, date)
 * takes the ids once and hides them from its inner parts.
 */
import { createContext, useContext } from 'react';

export interface FxFieldIds {
  /** The id the control takes (the label's `htmlFor`). */
  controlId: string;
  /** The visible label's id. */
  labelId: string;
  /** The message's id while the field shows one. */
  messageId?: string;
}

export const FxFieldContext = createContext<FxFieldIds | null>(null);

export function useFxFieldIds(): FxFieldIds | null {
  return useContext(FxFieldContext);
}

export interface FxNameInput {
  id?: string;
  ariaLabel?: string;
  ariaLabelledBy?: string;
  ariaDescribedBy?: string;
  /** Only for controls whose placeholder is not read as a name (dropdowns). */
  placeholder?: string;
}

export interface FxNameProps {
  id?: string;
  'aria-label'?: string;
  'aria-labelledby'?: string;
  'aria-describedby'?: string;
}

/** The naming attributes for a control (pure; `field` from `useFxFieldIds`). */
export function fxControlName(input: FxNameInput, field: FxFieldIds | null): FxNameProps {
  const id = input.id ?? field?.controlId;
  const describedBy = [input.ariaDescribedBy, field?.messageId].filter(Boolean).join(' ') || undefined;
  if (input.ariaLabel) return { id, 'aria-label': input.ariaLabel, 'aria-describedby': describedBy };
  if (input.ariaLabelledBy) return { id, 'aria-labelledby': input.ariaLabelledBy, 'aria-describedby': describedBy };
  if (field) return { id, 'aria-labelledby': field.labelId, 'aria-describedby': describedBy };
  if (input.id) return { id, 'aria-describedby': describedBy };
  return { id, 'aria-label': input.placeholder || undefined, 'aria-describedby': describedBy };
}

/** `fxControlName` for the control rendered here. */
export function useFxControlName(input: FxNameInput): FxNameProps {
  return fxControlName(input, useFxFieldIds());
}
