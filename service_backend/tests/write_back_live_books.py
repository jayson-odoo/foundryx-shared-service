"""Shared fixture: ``live_books_open`` models the future, reviewed code change that opens a live
book to write-back (plan 57 AC-57-22 / AC-57-47).

The write-time test-company check lives in ONE function,
``modules.autocount.write_back.guard.assert_test_company(db, tenant_id, company_id)``, which raises
``WriteConnectionError("WRITE_COMPANY_NOT_TEST")``. ``set_write_connection`` and every write frame
call it through the module attribute, so patching it here takes effect everywhere. Use the fixture
ONLY in a test that runs writes on a company holding SQL data on purpose; the write-time refusal
tests must not use it.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def live_books_open(monkeypatch):
    from modules.autocount.write_back import guard

    monkeypatch.setattr(guard, "assert_test_company", lambda *args, **kwargs: None, raising=False)
    yield
