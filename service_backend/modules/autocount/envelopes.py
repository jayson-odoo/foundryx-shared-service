"""Response envelopes - the per-entity unwrap strategy (AC-14-03, D1).

AutoCount returns **two different outer shapes**, and neither is derivable from
the other:

* **GRN** (``status_dict``) - a dict with a TOP-LEVEL ``Status`` and the rows
  under ``ResultTable``.
* **Masters** (``row_array``) - a **BARE ARRAY**. Each element is one record
  carrying its OWN ``Status``/``Message``/``RecordCount``, with the real DB row
  nested under ``Data[0]``.

Passing a master response through the GRN unwrap raises on every single row (it
requires a top-level ``Status`` that does not exist), so the strategy is selected
**per entity from config** - ``ac_entity_config.envelope`` - never branched
inside ``read()``. Adding a third envelope is a new class plus a registry entry:
``read()``'s signature and its callers do not change.

    !!  ONE ENVELOPE OWNS BOTH SUCCESS RULES, TOGETHER.  !!

``verdict()`` is the SINGLE decision about whether a response succeeded, and it
is consumed by both places that need that answer:

  * ``AutoCountClient._unwrap`` - decides whether the call RAISES.
  * ``AutoCountClient._record_call`` - decides how the call is BADGED in the
    activity log.

Those were two separate rules once. They disagreed on one reachable input (a
``200`` body with no ``Status`` key - AutoCount's own error envelope, which
carries only ``Message``): the call raised, and the activity log badged the leg
GREEN. So the run failed, the operator opened the exact leg the failure pointed
at, and saw no problem - the log at its least trustworthy precisely when it was
being relied on. Fixed in ``6d3e21c`` by making one mirror the other; kept fixed
here by structure rather than by comment, because there is now only one rule to
mirror.

**Do not add a success check to a caller.** If a new envelope needs a different
notion of success, that belongs in its ``verdict``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ── envelope keys (the values stored in ``ac_entity_config.envelope``) ────────
ENVELOPE_STATUS_DICT = "status_dict"
ENVELOPE_ROW_ARRAY = "row_array"
# Login is its own shape (a bare array of session dicts) and therefore its own
# envelope. Not stored in config - ``login()`` is not an entity read.
ENVELOPE_LOGIN = "login"

ENVELOPES = (ENVELOPE_STATUS_DICT, ENVELOPE_ROW_ARRAY)

_SUCCESS = "success"

# The vendor's per-row progress marker, seen as ``"1 of 106"`` on GRN.
#
#     !!  THIS IS NOT A TRUSTWORTHY TOTAL.  !!
# Verified live in slice 1: the total is computed AFTER the ``RecordCount`` cap
# is applied - an uncapped fetch reports ``"1 of 11"`` and a ``RecordCount:5``
# fetch reports ``"1 of 5"``. So it is surfaced to an operator as "what the
# vendor says is available" (AC-14-26) and is NEVER used to decide truncation;
# that decision stays ``len(records) == cap``.
_N_OF_M = re.compile(r"^\s*\d+\s+of\s+(?P<total>\d+)\s*$", re.IGNORECASE)


class UnknownEnvelope(Exception):
    """A configured envelope has no registered strategy. LOUD - silently falling
    back to the default would read a master response through the GRN unwrap and
    fail every row with a misleading error."""


@dataclass(frozen=True)
class Verdict:
    """The ONE success decision for a response body."""

    ok: bool
    message: Optional[str] = None


@dataclass
class Unwrapped:
    """A successful response, split into what the pipeline needs."""

    records: List[Dict[str, Any]] = field(default_factory=list)
    # What the vendor claims is available, when it says so at all. Reported
    # alongside the fetched count so "nothing changed" is distinguishable from
    # "the window excluded almost everything" (AC-14-26). Advisory only.
    reported_total: Optional[int] = None


def _reported_total(value: Any) -> Optional[int]:
    """Read the vendor's availability marker, in either shape it appears in.

    Returns None rather than guessing - an absent marker must read as "the
    vendor did not say", never as zero.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        raw = value.strip()
        match = _N_OF_M.match(raw)
        if match:
            return int(match.group("total"))
        if raw.isdigit():
            return int(raw)
    return None


class ResponseEnvelope:
    """One outer JSON shape. Subclasses own ``verdict`` + ``unwrap`` together."""

    key: str = ""

    def verdict(self, body: Any) -> Verdict:
        """Did this response succeed? The single rule (see module docstring)."""
        raise NotImplementedError

    def unwrap(self, body: Any) -> Unwrapped:
        """Records out of a body ``verdict`` has already approved."""
        raise NotImplementedError


class StatusDictEnvelope(ResponseEnvelope):
    """GRN and every slice-1 read: ``{"Status": "Success", "ResultTable": [...]}``.

    Success is ``Status == "Success"`` - NOT the HTTP code (business failures
    come back ``HTTP 200``) and NOT the presence of ``ResultTable`` (present but
    EMPTY on failure, so testing for it reads a failure as a successful empty
    fetch).
    """

    key = ENVELOPE_STATUS_DICT

    def verdict(self, body: Any) -> Verdict:
        if not isinstance(body, dict):
            return Verdict(False, "AutoCount returned an unexpected response shape.")
        # ``or ""`` collapses an ABSENT key to "", which is not "success" - so an
        # error envelope carrying only ``Message`` is a failure here. That
        # absent-key case is the one the two old rules disagreed on.
        declared = str(body.get("Status") or "")
        if declared.lower() != _SUCCESS:
            return Verdict(False, str(body.get("Message") or "").strip() or None)
        return Verdict(True)

    def unwrap(self, body: Any) -> Unwrapped:
        result = body.get("ResultTable")
        if result is None:
            result = []
        if not isinstance(result, list):
            raise ValueError("AutoCount returned a ResultTable that was not a list.")
        records = [row for row in result if isinstance(row, dict)]
        return Unwrapped(records=records, reported_total=_marker_total(records))


class RowArrayEnvelope(ResponseEnvelope):
    """Masters: a **BARE ARRAY** whose ELEMENTS are the records.

    Each element carries its own ``Status``/``Message``/``RecordCount`` beside
    flat fields, with the real DB row nested under ``Data[0]``. The whole element
    is the record - mapping rows address both levels explicitly
    (``EmailAddress`` vs ``Data.0.AutoKey``).

    A row that DECLARES a failure fails the WHOLE call, carrying that row's
    ``Message``. Accepting the good rows and dropping the bad ones would advance
    a watermark over records the vendor told us it could not give us - the
    silent-partial-sync failure AC-14-26 exists to prevent.

        !!  EMPTY ``Status`` IS SUCCESS ON THIS ROUTE. DO NOT "FIX" IT.  !!

    Masters do NOT use GRN's ``Status: "Success"`` convention. Verified live
    2026-07-21 against the demo instance: **all 106 Creditor rows and all 172
    Debtor rows return ``Status: ''`` with ``Message: ''``** - the empty string
    is what a healthy master row looks like. Only the GRN *dict* envelope
    declares ``"Success"``.

    So this must NOT mirror ``StatusDictEnvelope``'s ``!= "success" → fail``
    rule. Doing so rejects every valid row while the unit tests (which mock the
    payload) stay green - the whole master pipeline reads as broken against the
    real vendor. That is precisely the bug the first live smoke of this slice
    caught, after 205 mocked tests passed.

    The rule is therefore: a row fails only when it AFFIRMATIVELY says so - a
    non-empty ``Status`` that is not a success token. Silence means fine.
    """

    key = ENVELOPE_ROW_ARRAY

    def verdict(self, body: Any) -> Verdict:
        if isinstance(body, dict):
            # The vendor's error envelope for this route is still a dict, so
            # honour it rather than reporting a shape complaint.
            return Verdict(
                False,
                str(body.get("Message") or "").strip()
                or "AutoCount returned an error instead of the expected record array.",
            )
        if not isinstance(body, list):
            return Verdict(False, "AutoCount returned an unexpected response shape.")
        for row in body:
            if not isinstance(row, dict):
                continue
            declared = str(row.get("Status") or "").strip()
            # Empty == healthy on this route (see the class docstring). Only an
            # affirmative non-success token is a failure.
            if declared and declared.lower() != _SUCCESS:
                return Verdict(
                    False,
                    str(row.get("Message") or "").strip()
                    or f"AutoCount reported '{declared}' on one of the returned records.",
                )
        return Verdict(True)

    def unwrap(self, body: Any) -> Unwrapped:
        records = [row for row in body if isinstance(row, dict)]
        return Unwrapped(records=records, reported_total=_marker_total(records))


class LoginEnvelope(ResponseEnvelope):
    """``POST /api/Server/Login`` - a BARE ARRAY whose ``[0]`` is the session.

    It has an envelope of its own so the activity log badges a login leg by the
    login rule. Under the GRN rule a SUCCESSFUL login (an array, no ``Status``)
    would badge red; under no rule at all, a FAILED login (a dict carrying only
    ``Message``) badged green. ``login()`` still does its own JWT extraction -
    this governs the log verdict only.
    """

    key = ENVELOPE_LOGIN

    def verdict(self, body: Any) -> Verdict:
        if isinstance(body, dict):
            return Verdict(
                False,
                str(body.get("Message") or "").strip()
                or "AutoCount rejected the sign-in.",
            )
        if not isinstance(body, list) or not body or not isinstance(body[0], dict):
            return Verdict(
                False, "AutoCount's sign-in response was not the expected array."
            )
        return Verdict(True)

    def unwrap(self, body: Any) -> Unwrapped:
        return Unwrapped(records=[row for row in body if isinstance(row, dict)])


def _marker_total(records: List[Dict[str, Any]]) -> Optional[int]:
    """The availability marker off the FIRST record that carries one."""
    for row in records:
        total = _reported_total(row.get("RecordCount"))
        if total is not None:
            return total
    return None


# ── registry (D1: a third envelope is a class + a line, never a branch) ──────

_ENVELOPES: Dict[str, ResponseEnvelope] = {}


def register_envelope(envelope: ResponseEnvelope) -> None:
    _ENVELOPES[envelope.key] = envelope


def envelope_for(name: str) -> ResponseEnvelope:
    strategy = _ENVELOPES.get(name)
    if strategy is None:
        raise UnknownEnvelope(
            f"No AutoCount response envelope registered for '{name}'. "
            f"Known envelopes: {', '.join(sorted(_ENVELOPES))}."
        )
    return strategy


register_envelope(StatusDictEnvelope())
register_envelope(RowArrayEnvelope())
register_envelope(LoginEnvelope())

STATUS_DICT = envelope_for(ENVELOPE_STATUS_DICT)
ROW_ARRAY = envelope_for(ENVELOPE_ROW_ARRAY)
LOGIN = envelope_for(ENVELOPE_LOGIN)


def envelope_choices() -> Tuple[str, ...]:
    """Envelopes an entity may be configured with (login is not one)."""
    return ENVELOPES
