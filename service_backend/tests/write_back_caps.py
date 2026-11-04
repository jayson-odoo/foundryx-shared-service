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
    monkeypatch.setattr(
        capabilities,
        "VENDOR_CAPABILITIES",
        MappingProxyType({key: True for key in capabilities.VENDOR_CAPABILITIES}),
        raising=True,
    )
    yield
