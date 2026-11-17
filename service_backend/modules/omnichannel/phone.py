"""Shared phone-digits normalization (plan 26 S1, D-A2-9).

ONE `digits_only` helper backing `Contact.phone_digits` - maintained on every
write path that sets `phone` (inbound stitch, gateway create; manual
create/importer land in S2/S3) - and the within-workspace phone lookup
(`ContactRepository.find_by_phone_digits`). Centralising the normalization
here means a value written by one write path always matches a lookup issued
by another (AC-CTM-27's stitch-equivalence contract).

Empty digits (a malformed `wa_id`, a phone with no digits at all) intentionally
normalize to `""` - callers must NOT treat `""` as a wildcard match (the
`find_by_phone_in_workspace` no-match rule predates this module and stays).
"""
from typing import Optional


def digits_only(value: Optional[str]) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


# The calling code a number typed in local form ("012-345 6789") is read with.
# Malaysia (lane FEEDBACK-SUBSCRIBE R5); no tenant country setting exists yet.
DEFAULT_CALLING_CODE = "60"


def international_digits(value: Optional[str], calling_code: str = DEFAULT_CALLING_CODE) -> str:
    """``digits_only`` read as an international number, so a person typing a
    phone the way they say it matches the WhatsApp-stored form: spaces, dashes,
    brackets and "+" are ignored (``digits_only``), a leading "00" is the
    international prefix, and a single leading "0" is a local number in
    ``calling_code`` ("012-345 6789" -> "60123456789")."""
    digits = digits_only(value)
    if digits.startswith("00"):
        return digits[2:]
    if digits.startswith("0"):
        return f"{calling_code}{digits[1:]}"
    return digits


def local_digits_variant(digits: str, calling_code: str = DEFAULT_CALLING_CODE) -> str:
    """The local-form spelling ("0" + national number) of an international
    ``digits`` in ``calling_code``, or ``""``: lets a lookup also hit a legacy
    row whose stored digits kept the local "0" form."""
    if digits.startswith(calling_code) and len(digits) > len(calling_code):
        return f"0{digits[len(calling_code):]}"
    return ""
