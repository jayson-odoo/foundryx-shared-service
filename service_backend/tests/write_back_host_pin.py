"""Shared autouse fixture for the write-back tests: the write guard pins the
wrapper host to a hashed allowlist, so a test host is added to it (by hash)
for the duration of each test. Tolerates a guard that has no allowlist yet."""

from __future__ import annotations

import hashlib

import pytest

TEST_HOST = "ac.example.test"
TEST_HOST_SHA256 = hashlib.sha256(TEST_HOST.encode("utf-8")).hexdigest()


@pytest.fixture(autouse=True)
def pin_test_write_host(monkeypatch):
    from modules.autocount.write_back import guard

    current = getattr(guard, "ALLOWED_WRITE_HOST_SHA256", frozenset())
    monkeypatch.setattr(
        guard,
        "ALLOWED_WRITE_HOST_SHA256",
        frozenset(set(current) | {TEST_HOST_SHA256}),
        raising=False,
    )
    yield
