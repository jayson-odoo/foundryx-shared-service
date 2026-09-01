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

from modules.autocount.services.company_service import SEEDED_ENTITIES

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
    """Members of `export const X: string[] = ['a', 'b'];` (single-line)."""
    match = re.search(rf"export const {const_name}[^=]*=\s*\[([^\]]*)\]", src)
    assert match, f"{const_name} array not found in autocount-meta.ts"
    return set(re.findall(r"'([a-z_]+)'", match.group(1)))


def test_ac_api_capable_entity_types_matches_the_backend_seeded_entities():
    src = TS_PATH.read_text()
    ts_capable = _string_array(src, "AC_API_CAPABLE_ENTITY_TYPES")
    assert ts_capable == set(SEEDED_ENTITIES)
