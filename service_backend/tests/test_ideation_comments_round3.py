"""Plan 19 fix round 3 - RED tests (AC-19-47 parentId shape, AC-19-48 surrogate keys in the 422 echo)."""
import json
import uuid

import pytest

from tests.test_ideation_comments_round2 import (  # noqa: F401
    _bearer,
    _mint,
    _pub_post,
    _pub_url,
    _raw,
    _seed,
    _seed_connection,
    _tok,
    _url,
    ideation_client,
    setup,
)

# Raw JSON text so a lone-surrogate ESCAPE reaches the server.
BAD_PARENTS = ['"\\ud800"', '"not-a-uuid"', '"../x"']


def _body(parent_literal: str) -> str:
    return '{"body": "hi", "parentId": %s}' % parent_literal


@pytest.mark.parametrize("parent", BAD_PARENTS)
def test_ac_19_47_operator_rejects_malformed_parent_id(setup, parent):
    """Must be 422 (never 500, never a lookup)."""
    s = setup
    iid = _seed(s, _tok("h"))
    res = _raw(s["client"], "POST", _url(iid), _body(parent), s["h"])
    assert res.status_code == 422, res.text
    json.loads(res.text)  # valid JSON error body


@pytest.mark.parametrize("parent", BAD_PARENTS)
def test_ac_19_47_embed_rejects_malformed_parent_id(setup, parent):
    s = setup
    iid = _seed(s, _tok("i"))
    _seed_connection(s["factory"], product_id=s["product_id"])
    emb = _bearer(_mint(s["client"]))
    res = _raw(s["client"], "POST", f"/embed/ideas/{iid}/comments", _body(parent), emb)
    assert res.status_code == 422, res.text


@pytest.mark.parametrize("parent", BAD_PARENTS)
def test_ac_19_47_public_rejects_malformed_parent_id_without_burning_budget(setup, parent):
    s = setup
    _seed(s, _tok("j"))
    for _ in range(6):
        assert _raw(s["client"], "POST", _pub_url(_tok("j")), _body(parent)).status_code == 422
    for i in range(5):
        assert _pub_post(s["client"], _tok("j"), f"ok{i}").status_code == 201


def test_ac_19_47_well_formed_unknown_uuid_parent_stays_404(setup):
    s = setup
    iid = _seed(s, _tok("k"))
    ghost = str(uuid.uuid4())
    assert _raw(s["client"], "POST", _url(iid), _body(f'"{ghost}"'), s["h"]).status_code == 404
    _seed(s, _tok("l"), idea_number="IDEA-1950")
    assert _raw(s["client"], "POST", _pub_url(_tok("l")), _body(f'"{ghost}"')).status_code == 404


# ── AC-19-48: lone surrogate as a JSON KEY must not 500 the 422 echo ──────────
SURROGATE_KEY = '{"\\ud800": "x"}'


def test_ac_19_48_operator_surrogate_key_is_422_with_valid_json(setup):
    s = setup
    iid = _seed(s, _tok("m"))
    res = _raw(s["client"], "POST", _url(iid), SURROGATE_KEY, s["h"])
    assert res.status_code == 422, res.text
    json.loads(res.text)


def test_ac_19_48_public_surrogate_key_is_422_with_valid_json(setup):
    s = setup
    _seed(s, _tok("n"))
    res = _raw(s["client"], "POST", _pub_url(_tok("n")), SURROGATE_KEY)
    assert res.status_code == 422, res.text
    json.loads(res.text)
