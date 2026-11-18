/**
 * Foundryx UIUX fields (slice F4, playbook-uiux.md). Most pages get these
 * without edits: `Input`, `Textarea`, `Select`, `SearchSelect`, `MultiSelect`,
 * `DateInput`, `Calendar`, `DateRangePicker`, `ToggleGroup`, `Tabs`,
 * `Slider`, `Switch` and `SecretInput` render them while the switch is on.
 * The rest are new building blocks a page uses under `useFx()`.
 */
export { FxField, FxFieldMessage, FxInput, FxNoteField, FxTextarea } from './fx-input';
export { FxSearchSelect } from './fx-search-select';
export { FxMultiSelect } from './fx-multi-select';
export { FxCalendar } from './fx-calendar';
export { FX_DATE_HINT, FxDateField, type FxDateFieldProps } from './fx-date-field';
export { FX_RANGE_PICKS, FxDateRangePicker, fxRangeLabel, resolveFxPresetRange } from './fx-date-range-picker';
export { FxDayLine, FxMoment, FxZoneLine } from './fx-moment';
export { FX_MONEY_HINT, FxMoneyField, type FxMoneyFieldProps } from './fx-money-field';
export { FxStepper, FxValueCardStepper, type FxStepperProps } from './fx-stepper';
export { FxToggleGroup, FxToggleGroupItem, nextSegmentValue } from './fx-toggle-group';
export { FxTabsContent, FxTabsList, FxTabsTrigger } from './fx-tabs';
export { FxSlider, FxSliderThumb } from './fx-slider';
export { FxSwitch } from './fx-switch';
export { FX_COPIED_MS, FxSavedSecret, FxSecretInput, FxSecretOnce } from './fx-secret';
export { FxPasswordStrength } from './fx-password-strength';
