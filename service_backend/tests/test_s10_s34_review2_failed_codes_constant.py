"""Sprint-5/10 S3+S4 review round 2 - MUST-FIX 1 (item 1): ``BUILD_ABANDONED``
is a genuine FIFTH failed-status code (AC-10-88), never folded into
``SOURCE_PAGE_FAILED`` (that would misreport an orphan-reclaimed build as a
source fault). ONE named constant tuple,
``modules.autocount.sync.PULL_SNAPSHOT_FAILED_CODES``, is now the single
source of truth the classifier, the orphan-sweep hook (``bootstrap.py``) and
the gateway's own pinned test (``test_s10_s4_gateway_errors_and_audit.py``,
amended in the SAME commit to import this constant rather than hand-typing
the set) all read.

RED before the fix: ``modules.autocount.sync`` has no
``PULL_SNAPSHOT_FAILED_CODES`` attribute at all - every test below fails at
collection/attribute-access with an ``AttributeError``/``ImportError``.
"""
from __future__ import annotations


def test_the_constant_is_exactly_the_pinned_codes():
    from modules.autocount import sync as sync_module

    # review round 4 (SF-3) - a SIXTH code, ``COMBINE_RULE_FAILED``: a
    # ``combine`` drop rule that raises at runtime during a pull build
    # (AC-10-79) is a genuine extraction failure, never folded onto
    # ``SOURCE_PAGE_FAILED`` either, for the SAME "an operator debugging
    # the failure needs to land on the actual cause" reasoning as
    # ``BUILD_ABANDONED``.
    assert set(sync_module.PULL_SNAPSHOT_FAILED_CODES) == {
        "SOURCE_PAGE_FAILED",
        "ENRICH_FAILED",
        "ROW_LIMIT",
        "EMPTY_EXTRACT",
        "BUILD_ABANDONED",
        "COMBINE_RULE_FAILED",
    }
    assert "MAPPING_FAILED" not in sync_module.PULL_SNAPSHOT_FAILED_CODES


def test_the_classifier_never_returns_a_code_outside_the_constant():
    from modules.autocount import sync as sync_module
    from modules.autocount.http_source.errors import HttpSourceError

    for exc in (
        HttpSourceError("boom", code="row_limit"),
        HttpSourceError("boom", phase="enrich"),
        HttpSourceError("boom"),
    ):
        code = sync_module._classify_http_source_error(exc)
        assert code in sync_module.PULL_SNAPSHOT_FAILED_CODES


def test_bootstrap_on_job_orphaned_uses_the_named_constant_not_a_bare_literal():
    """A source-level control: ``bootstrap.py`` must reference
    ``sync.ERROR_CODE_BUILD_ABANDONED`` (or the tuple itself), never a
    hand-typed ``"BUILD_ABANDONED"`` string that could silently drift from
    the pinned constant."""
    import inspect

    from modules.autocount import bootstrap as bootstrap_module

    source = inspect.getsource(bootstrap_module.on_job_orphaned)
    assert '"BUILD_ABANDONED"' not in source, (
        "on_job_orphaned must use the named sync constant, not a bare literal"
    )


def test_sync_no_longer_hand_types_the_empty_extract_literal():
    """A source-level control for the review's own instruction: the bare
    ``"EMPTY_EXTRACT"`` literal at the zero-row guard must be replaced by the
    named constant."""
    import inspect

    from modules.autocount import sync as sync_module

    source = inspect.getsource(sync_module._run_pull_snapshot)
    assert '"EMPTY_EXTRACT"' not in source
    assert "ERROR_CODE_EMPTY_EXTRACT" in source
