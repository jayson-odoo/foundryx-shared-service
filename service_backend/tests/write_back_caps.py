"""Opt-in fixture: turn every vendor capability flag ON for one test.

The unlink / SPO-unlink paths are gated off while AutoCount does not honour
them; tests that exercise those paths request this fixture explicitly. A no-op
while the capabilities module does not exist yet."""

from __future__ import annotations

from types import MappingProxyType

import pytest


@pytest.fixture
def vendor_caps_all_on(monkeypatch):
    try:
        from modules.autocount.write_back import capabilities
    except ImportError:
        yield
        return
    # Plan 57: the plan 55 flags (link_existing_row / unlink / spo_unlink) retire; the
    # per kind table replaces them. Flip whichever of the two exists.
    legacy = getattr(capabilities, "VENDOR_CAPABILITIES", None)
    if legacy is not None:
        monkeypatch.setattr(
            capabilities, "VENDOR_CAPABILITIES",
            MappingProxyType({key: True for key in legacy}), raising=True,
        )
    table = getattr(capabilities, "CAPABILITIES", None)
    if table is not None:
        monkeypatch.setattr(
            capabilities, "CAPABILITIES",
            MappingProxyType({key: True for key in table}), raising=True,
        )
    yield
