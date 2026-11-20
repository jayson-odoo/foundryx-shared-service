"""Flat-row mapping profile for the ``sql_db`` source (AC-22-09/10).

A DB task's rows are FLAT (``acc_no``), not the vendor's nested envelope
(``Data.0.AutoKey``), so the source path is the result column name and the
``source_ref`` is minted from the task's key columns.

The load-bearing test in here is the PARITY one: a company that already synced
customers over the API path and then switches to the DB path must mint the
SAME ``source_ref``, or Sorento's ``(source_system, entity_type, source_ref)``
uniqueness sees brand-new records and a duplicate ``created`` wave lands on a
live consumer (AC-22-10).
"""
from __future__ import annotations

import pytest

from modules.autocount.canonical.masters import ENTITY_CUSTOMER, ENTITY_SUPPLIER
from modules.autocount.mapping import (
    IdentityError,
    MappingEngine,
    MappingRow,
    company_qualified_identity,
    flat_profile,
    flat_source_ref,
)
from modules.autocount.services.etl_service import ENTITY_SALES_AGENT

DB = "AED_VSOFT"


# ── source_ref minting (AC-22-10, Appendix A6 §6) ────────────────────────────


def test_a_flat_ref_is_company_qualified_from_the_key_columns():
    assert flat_source_ref(
        {"AutoKey": 7, "AccNo": "300-A001"},
        database_name=DB,
        key_columns=["AutoKey"],
        entity_type=ENTITY_CUSTOMER,
    ) == "AED_VSOFT:7"


def test_a_composite_key_joins_on_a_pipe():
    assert flat_source_ref(
        {"Co": "01", "AccNo": "300-A001"},
        database_name=DB,
        key_columns=["Co", "AccNo"],
        entity_type=ENTITY_CUSTOMER,
    ) == "AED_VSOFT:01|300-A001"


def test_the_db_path_mints_the_SAME_ref_as_the_api_path():
    """AC-22-10 - the whole point. The API path reads ``Data.0.AutoKey`` out of
    the vendor envelope; the DB path reads an ``AutoKey`` COLUMN. Same company,
    same key, same string - so a switched-over company dry-runs as
    ``updated``, never as a duplicate ``created`` wave."""
    api_row = {"AccNo": "300-A001", "Data": [{"AutoKey": 7, "LastModified": "x"}]}
    db_row = {"AutoKey": 7, "AccNo": "300-A001", "CompanyName": "Acme"}
    assert flat_source_ref(
        db_row, database_name=DB, key_columns=["AutoKey"], entity_type=ENTITY_CUSTOMER
    ) == company_qualified_identity(api_row, DB)


def test_a_sales_agent_ref_is_deliberately_NOT_company_qualified():
    """Appendix A6 §6: Sorento's ``sales_agents`` rows are SHARED
    (``company_id`` NULL), so two companies pushing the same agent under
    different refs makes the second one ``failed``. One scheme, one row."""
    assert flat_source_ref(
        {"AgentCode": " sa01 "},
        database_name=DB,
        key_columns=["AgentCode"],
        entity_type=ENTITY_SALES_AGENT,
    ) == "agent:SA01"


def test_a_composite_sales_agent_key_still_upper_trims_every_part():
    assert flat_source_ref(
        {"a": " x ", "b": "y"},
        database_name=DB,
        key_columns=["a", "b"],
        entity_type=ENTITY_SALES_AGENT,
    ) == "agent:X|Y"


def test_a_blank_key_value_is_a_named_error_not_a_silent_ref():
    """A ref built from a blank key would correlate every blank-key row onto
    ONE consumer record and overwrite it repeatedly."""
    with pytest.raises(IdentityError):
        flat_source_ref(
            {"AutoKey": None},
            database_name=DB,
            key_columns=["AutoKey"],
            entity_type=ENTITY_CUSTOMER,
        )
    with pytest.raises(IdentityError):
        flat_source_ref(
            {"AutoKey": "   "},
            database_name=DB,
            key_columns=["AutoKey"],
            entity_type=ENTITY_CUSTOMER,
        )


def test_no_key_columns_is_a_named_error():
    with pytest.raises(IdentityError):
        flat_source_ref(
            {"AutoKey": 7}, database_name=DB, key_columns=[], entity_type=ENTITY_CUSTOMER
        )


def test_a_missing_company_name_is_a_named_error_for_a_qualified_entity():
    with pytest.raises(IdentityError):
        flat_source_ref(
            {"AutoKey": 7}, database_name="", key_columns=["AutoKey"],
            entity_type=ENTITY_CUSTOMER,
        )


# ── the profile through the REAL MappingEngine (AC-22-09) ────────────────────


def _rows(*specs):
    return [
        MappingRow(
            source_path=source,
            canonical_field=target,
            transform=transform,
            formula=formula,
        )
        for source, target, transform, formula in specs
    ]


def test_flat_columns_map_through_the_real_engine_with_no_Data_0_synthesis():
    engine = MappingEngine(
        _rows(
            ("acc_no", "code", "string", None),
            ("company_name", "name", "string", None),
            ("email", "email", "string", None),
        ),
        entity_type=ENTITY_CUSTOMER,
        profile=flat_profile(ENTITY_CUSTOMER, ["acc_no"]),
        database_name=DB,
    )
    mapped = engine.map_document(
        {"acc_no": "300-A001", "company_name": "Acme", "email": "a@b.c"}
    )
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.source_ref == "AED_VSOFT:300-A001"
    assert mapped.record.code == "300-A001"
    assert mapped.record.name == "Acme"
    # The human-facing number comes off the FIRST key column, not ``AccNo``.
    assert mapped.doc_no == "300-A001"


def test_a_formula_row_works_unchanged_on_a_flat_row():
    """Slice-16 formulas are transform-level and know nothing about the source
    shape - the DB path must not need its own evaluator (AC-22-09)."""
    engine = MappingEngine(
        _rows(
            ("acc_no", "code", "string", None),
            ("company_name", "name", "string", None),
            ("status", "is_active", "boolean", "upper(value) == 'A'"),
        ),
        entity_type=ENTITY_CUSTOMER,
        profile=flat_profile(ENTITY_CUSTOMER, ["acc_no"]),
        database_name=DB,
    )
    live = engine.map_document({"acc_no": "1", "company_name": "A", "status": "a"})
    dead = engine.map_document({"acc_no": "2", "company_name": "B", "status": "x"})
    assert live.ok and live.record.is_active is True
    assert dead.ok and dead.record.is_active is False


def test_the_flat_profile_keeps_the_entity_s_canonical_model():
    """The profile changes IDENTITY and PATHS, never the canonical shape - the
    sink still receives a CanonicalSupplier/CanonicalCustomer."""
    from modules.autocount.canonical.masters import CanonicalCustomer, CanonicalSupplier

    assert flat_profile(ENTITY_CUSTOMER, ["a"]).record_model is CanonicalCustomer
    assert flat_profile(ENTITY_SUPPLIER, ["a"]).record_model is CanonicalSupplier
