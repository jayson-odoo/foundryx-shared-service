# Import engine - deep reference

The narrative overview (per-entity `ImporterDef`, two-phase Test/Import,
`id`-only matching, multi-format reader, export/import symmetry) lives in the
root `CLAUDE.md` "Import engine" section - read that first. This file carries
only the topic-specific notes that don't fit there.

## Round-trip CSV formula-injection guard (`coerce.py` strips the export sanitizer's guard)

Every cell the import engine WRITES to a generated file (template + annotated
error file) is sanitized against formula injection: `sanitize.sanitize_cell`
(`app/import_engine/sanitize.py`) prefixes a value with a leading `'` when the
value itself starts with `=`/`+`/`-`/`@`/tab/CR - a cell like `=SUM(A1:A9)`
would otherwise execute as a formula when the generated file is opened in
Excel/Sheets. The frontend mirror of this rule is `lib/csv.ts` (house-wide,
not import-engine-specific).

**On the way back in, `coerce.py`'s `_strip_formula_guard` undoes exactly this
one guard for TEXT columns house-wide** - re-importing one of our own
exports/templates must round-trip the ORIGINAL value, not a value with a
stray literal `'` glued onto the front. A CSV genuinely stores that `'` as a
literal character (unlike a native XLSX cell's text-format flag, which is
metadata, not a character), so on read `coerce_string` strips exactly one
leading `'` **only when the character right after it is one of the guarded
prefixes** (`_DANGEROUS_PREFIXES` in `sanitize.py`) - a genuine value that
happens to start with an apostrophe (`'Ohana Co`) is left untouched, since the
character after the apostrophe there is `O`, not a guarded prefix.

This pairing (`sanitize_cell` on write, `_strip_formula_guard` on read) is the
reason export -> edit -> re-import round-trips cleanly for every text column,
not just the columns a given importer happens to test.
