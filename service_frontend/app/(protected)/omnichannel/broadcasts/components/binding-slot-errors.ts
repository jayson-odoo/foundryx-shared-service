/** Tester O-4: pull the server-mapped 422 message for one binding slot
 *  (`bindings.<group>.<index>.text|fallback|field`) out of RHF's nested
 *  error tree. `TemplateBinding` is a discriminated union (static | contact
 *  field), so a slot's error could land on `.text`, `.fallback` or `.field`
 *  depending on which variant is selected - read defensively via `unknown`
 *  rather than fighting RHF's union-narrowed `FieldErrors` typing. */
export function bindingSlotErrors(
  errors: unknown,
  group: 'header' | 'body' | 'buttons',
  count: number,
): (string | undefined)[] {
  const bindingsErrors = (errors as { bindings?: Record<string, unknown> } | undefined)?.bindings;
  const groupErrors = bindingsErrors?.[group] as
    | Array<Record<string, { message?: string }> | undefined>
    | undefined;
  return Array.from({ length: count }, (_, i) => {
    const row = groupErrors?.[i];
    return row?.text?.message ?? row?.fallback?.message ?? row?.field?.message;
  });
}
