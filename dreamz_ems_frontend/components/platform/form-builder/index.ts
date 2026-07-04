/**
 * Form-builder public API (plan sprint-3/01 D6/D7/D18) — the drag-drop form
 * designer. The owning ResourceForm passes the draft `FormDocument` + an Edit
 * toggle; the builder emits the edited doc. Editor-agnostic: the document
 * (types/forms.ts) is the only contract.
 */
export { FormBuilder } from './form-builder';
export type { FormBuilderProps } from './form-builder';
