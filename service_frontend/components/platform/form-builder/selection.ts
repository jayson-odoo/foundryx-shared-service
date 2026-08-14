/**
 * Builder selection model (plan sprint-3/01) - exactly one of page / section /
 * field is selected at a time (FlowCanvas single-selection precedent); the
 * settings panel renders contextually off it.
 */
export type BuilderSelection =
  | { kind: 'page'; id: string }
  | { kind: 'section'; id: string }
  | { kind: 'field'; id: string }
  | null;
