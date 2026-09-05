"""Frontend <-> backend AC_API_CAPABLE_ENTITY_TYPES parity (plan 22 S4 review S2).

``EntitySourceDialog`` (frontend) only offers the "AutoCount API" source for
an entity this build has a confirmed, observed vendor payload for -
``AC_API_CAPABLE_ENTITY_TYPES`` in ``autocount-meta.ts``. The backend enforces
the SAME set server-side via ``CompanyService.SEEDED_ENTITIES``
(``update_entity_config``'s 422 guard). The two copies must never drift - an
entity added to one without the other either lets the frontend offer a
guaranteed-to-fail switch, or has the backend silently refuse a switch the
frontend still shows as available. This test pins them together (the
``test_form_parity.py``/``test_frontend_defaults_parity`` precedent - read the
actual TS source, not a duplicated literal, so an edit to either side that
forgets the other fails LOUDLY here rather than drifting quietly.
"""
import re
from pathlib import Path

from modules.autocount.canonical.grn import ENTITY_GOODS_RECEIVED_NOTE
from modules.autocount.mapping import ENTITY_PROFILES
from modules.autocount.services.company_service import SEEDED_ENTITIES
from modules.autocount.services.etl_service import ETL_ENTITY_TYPES

TS_PATH = (
    Path(__file__).resolve().parents[2]
    / "service_frontend"
    / "app"
    / "(protected)"
    / "autocount"
    / "components"
    / "autocount-meta.ts"
)


def _string_array(src: str, const_name: str) -> set:
    """Members of `export const X: string[] = ['a', 'b'];` (single- or
    multi-line - the bracket body is matched non-greedily up to the first
    ``]``, which a flat string array never contains)."""
    match = re.search(rf"export const {const_name}[^=]*=\s*\[([^\]]*)\]", src, re.S)
    assert match, f"{const_name} array not found in autocount-meta.ts"
    return set(re.findall(r"'([a-z_]+)'", match.group(1)))


def test_ac_api_capable_entity_types_matches_the_backend_seeded_entities():
    src = TS_PATH.read_text()
    ts_capable = _string_array(src, "AC_API_CAPABLE_ENTITY_TYPES")
    assert ts_capable == set(SEEDED_ENTITIES)


def test_ac_sql_db_entity_types_is_every_extractable_entity_minus_grn():
    """Plan sprint-5/01 AC-01-17: a DB company's Add-entity picker offers EVERY
    entity a database task can extract AND mapping can shape - ``ENTITY_PROFILES``
    (= ``ETL_ENTITY_TYPES``) minus GRN, which has no Sorento path and an
    API-only envelope (AC-01-10). Ten with `shipping_order` (sprint-5/02,
    AC-02-10); an entity added to either side without the other fails LOUDLY
    here.

    RED until AC-02-10 lands: today neither `ENTITY_PROFILES`/
    `ETL_ENTITY_TYPES` nor `autocount-meta.ts`'s `AC_SQL_DB_ENTITY_TYPES`
    carry `shipping_order` yet, so this fails at 9, not 10.
    """
    src = TS_PATH.read_text()
    ts_sql_db = _string_array(src, "AC_SQL_DB_ENTITY_TYPES")
    assert ts_sql_db == set(ENTITY_PROFILES) - {ENTITY_GOODS_RECEIVED_NOTE}
    assert ts_sql_db == set(ETL_ENTITY_TYPES) - {ENTITY_GOODS_RECEIVED_NOTE}
    assert len(ts_sql_db) == 10, (
        "AC_SQL_DB_ENTITY_TYPES must include shipping_order (AC-02-10) - "
        f"got {len(ts_sql_db)}: {sorted(ts_sql_db)}"
    )
    assert "shipping_order" in ts_sql_db, (
        "AC_SQL_DB_ENTITY_TYPES is missing shipping_order (AC-02-10)"
    )
