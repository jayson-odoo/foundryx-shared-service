/**
 * Form runtime renderer public API (plan sprint-3/01). Pinned surface another
 * session compiles against - the renderer plus its file-staging escape hatch
 * (Phase B upload wiring resolves `local:` answer keys via `stagedFile`).
 */
export { FormRenderer } from './form-renderer';
export type { FormRendererProps } from './form-renderer';
export { stagedFile } from './file-input';
export { COUNTRIES, countryName } from './countries';
export type { Country } from './countries';
