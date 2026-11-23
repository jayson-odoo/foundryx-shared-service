"""Plan 73 fix round 1 (F1, F2, F4): the note splice, a refusal after a landed PUT, the recover path."""

from __future__ import annotations

import pytest

from modules.autocount.write_back import payloads as P

NOTE = "**ACME S/O: 389293 DD: 04/11/2026"
BODY = r"{\rtf1\ansi\deff0\pard\f0\fs20 Special\par{\pict\pngblip 8950}\par"


@pytest.mark.parametrize("tail", ["\r\n", "\x00", "  ", "\r\n\x00"])
def test_append_note_keeps_the_note_inside_the_group_and_the_trailing_bytes_after_it(tail):
    fd = BODY + "}" + tail
    out = P.append_note(fd, NOTE)
    assert out == BODY + "\\par " + NOTE + "}" + tail
    assert P.append_note(out, NOTE) == out  # idempotent


def test_append_note_a_plain_closing_brace_is_unchanged_behaviour():
    fd = BODY + "}"
    assert P.append_note(fd, NOTE) == BODY + "\\par " + NOTE + "}"
