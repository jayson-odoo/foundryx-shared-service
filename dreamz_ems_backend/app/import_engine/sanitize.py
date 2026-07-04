"""Formula-injection sanitization (sprint-3/09 D14).

Every cell we WRITE to a generated file (template + annotated error file) is
sanitized: a value leading with ``= + - @`` / tab / CR could be executed as a
formula when the file is opened in Excel/Sheets. Prefix such values with ``'``
so they render as literal text. Server equivalent of frontend ``lib/csv.ts``.
"""
_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_cell(value):
    """Return a spreadsheet-safe string for any cell we emit."""
    if value is None:
        return ""
    s = str(value)
    if s and s[0] in _DANGEROUS_PREFIXES:
        return "'" + s
    return s
