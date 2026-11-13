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
