"""Sprint-5/10 S4 - pull API key issuance + resolution: AC-10-27, 28, 47.

Mirrors the omnichannel precedent (`modules/omnichannel/services/
api_key_service.py`, `tests/test_omnichannel_api_gateway.py`'s own key-mint
assertions) byte for byte in SPIRIT - scheme, hashing, constant-time compare,
plaintext-once - but is its OWN module (D9: cross-module table reads are
forbidden, so this is a deliberate, acknowledged duplication, BL-SS-210).

RED before the coder: `modules.autocount.services.pull_key_service` and
`modules.autocount.models.AcPullApiKey` do not exist at all yet - every
import below fails at collection with a plain `ImportError`.

ASSUMED NAMES the coder must conform to (none pinned elsewhere on this
branch):

* `modules.autocount.models.AcPullApiKey` (table `ac_pull_api_key`): `id,
  tenant_id, name, key_prefix (indexed), key_hash, company_ids (JSON list of
  company ids), created_by, created_at, last_used_at, revoked_at` (AC-10-27
  verbatim).
* `modules.autocount.services.pull_key_service`:
  - `KEY_SCHEME = "fxa_live_"`, `PREFIX_LEN = 8`.
  - `PullKeyService(db).issue(tenant_id, *, name, company_ids,
    created_by=None) -> Tuple[AcPullApiKey, str]` - the second element is the
    PLAINTEXT key, returned ONLY here, never persisted or re-derivable.
  - `PullKeyService(db).resolve(presented_key: str) -> Optional[AcPullApiKey]`
    - deliberately NOT tenant-scoped as an input (tenant is DERIVED from the
      resolved key, mirroring `ApiKeyService.resolve`) - looks up by the
      8-char prefix, then `hmac.compare_digest` on the sha256 hash; returns
      `None` for malformed/wrong-scheme/unknown/revoked, uniformly.
      (Sprint-5/10 S6, AC-10-58 L5: the `last_used_at` stamp moved OUT of
      `resolve` into `PullKeyService.mark_used`, which
      `pull_auth.resolve_pull_key` calls only once the service gate passes -
      a suspended tenant's key must not record a call it never got served.
      Pinned by `test_s10_s6_security_fixes.py`.)
  - `PullKeyService(db).revoke(tenant_id, key_id) -> AcPullApiKey` - raises
    `PullKeyNotFound` (exported from the same module) for an unknown id OR
    one belonging to another tenant (the polymorphic-id rule: revoke is
    ALWAYS tenant-scoped, unlike `resolve`).
  - `PullKeyService(db).list_for_tenant(tenant_id) -> List[AcPullApiKey]`.
* `modules.autocount.repositories.autocount_repository.PullKeyRepository`
  mirrors `PullSnapshotRepository`'s own scoping discipline (AC-10-47): every
  method that takes a `key_id` ALSO takes `tenant_id`, except the one
  prefix-lookup method `resolve` genuinely needs to be unscoped (tenant is
  not yet known) - pinned as the ONE deliberate exception, not an oversight.

Kill-test notes are per section below.
"""
from __future__ import annotations

import hashlib

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.tenant import Tenant


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network. See
    `test_s10_s3_delivery_mode.py`'s copy of this fixture for the full
    rationale (coordinator finding 2026-09-20)."""
    import httpx

    real_send = httpx.Client.send
    real_async_send = httpx.AsyncClient.send

    def guarded_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return real_send(self, request, *args, **kwargs)

    async def guarded_async_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return await real_async_send(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", guarded_send)
    monkeypatch.setattr(httpx.AsyncClient, "send", guarded_async_send)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


OTHER_TENANT = "tenant-other-s10-s4-keys"


def _other_tenant(db) -> None:
    if db.get(Tenant, OTHER_TENANT) is None:
        default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(
            Tenant(
                id=OTHER_TENANT, slug="other-s10-s4-keys", name="Other Co",
                status_id=default_tenant.status_id,
            )
        )
        db.commit()


def _company(
    db, tenant_id=DEFAULT_TENANT_ID, *, database_name="AED_SORENTO", sorento_company_code="SRT",
):
    """Security round 1 HIGH 2 knock-on: `PullKeyService.issue` now validates
    every `company_ids` entry against a REAL, tenant-scoped `AcCompany` row -
    a fake placeholder like `"co-1"` is rightly refused. Distinct
    `database_name`/`sorento_company_code` per call avoid
    `uq_ac_company_tenant_db` (bit the last tester when two companies in the
    SAME tenant shared a `database_name`)."""
    from app.models.connection import Connection
    from modules.autocount.models import AcCompany

    conn = Connection(
        tenant_id=tenant_id, provider="autocount", type="erp", name=f"db1 REST {database_name}",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    company = AcCompany(
        tenant_id=tenant_id, connection_id=conn.id, database_name=database_name,
        company_name="Sorento", name="Sorento", is_active=True,
        sorento_company_code=sorento_company_code,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


# ── AC-10-28: issuance - scheme, hashing, plaintext-once ─────────────────────


def test_issue_returns_a_plaintext_key_with_the_right_scheme(db):
    from modules.autocount.services.pull_key_service import KEY_SCHEME, PullKeyService

    company = _company(db)
    key, plaintext = PullKeyService(db).issue(
        DEFAULT_TENANT_ID, name="SRT integration", company_ids=[company.id],
    )
    assert plaintext.startswith(KEY_SCHEME)
    assert key.name == "SRT integration"
    assert key.company_ids == [company.id]
    assert key.revoked_at is None
    assert key.last_used_at is None


def test_issue_stores_only_a_hash_and_an_8_char_prefix_never_the_plaintext(db):
    from modules.autocount.services.pull_key_service import (
        KEY_SCHEME,
        PREFIX_LEN,
        PullKeyService,
    )

    company = _company(db)
    key, plaintext = PullKeyService(db).issue(
        DEFAULT_TENANT_ID, name="k", company_ids=[company.id],
    )
    assert len(key.key_prefix) == PREFIX_LEN
    assert key.key_prefix == plaintext[len(KEY_SCHEME) : len(KEY_SCHEME) + PREFIX_LEN]
    assert len(key.key_hash) == 64  # sha256 hexdigest
    assert key.key_hash != plaintext
    assert key.key_hash == hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def test_two_issued_keys_never_collide(db):
    from modules.autocount.services.pull_key_service import PullKeyService

    company = _company(db)
    _key1, plaintext1 = PullKeyService(db).issue(
        DEFAULT_TENANT_ID, name="a", company_ids=[company.id],
    )
    _key2, plaintext2 = PullKeyService(db).issue(
        DEFAULT_TENANT_ID, name="b", company_ids=[company.id],
    )
    assert plaintext1 != plaintext2


# ── AC-10-28: resolution - constant-time, uniform-miss, last_used_at ────────


def test_resolve_a_freshly_issued_key_returns_its_row_and_mark_used_stamps_it(db):
    """Sprint-5/10 S6 (AC-10-58 L5) - `resolve` no longer stamps on its own;
    `mark_used` does, and only `pull_auth.resolve_pull_key` calls it, after
    the service gate. The end state for a SERVED call is unchanged."""
    from modules.autocount.services.pull_key_service import PullKeyService

    service = PullKeyService(db)
    company = _company(db)
    key, plaintext = service.issue(DEFAULT_TENANT_ID, name="k", company_ids=[company.id])
    assert key.last_used_at is None  # control: unstamped before any resolve

    resolved = service.resolve(plaintext)
    assert resolved is not None
    assert resolved.id == key.id
    assert resolved.last_used_at is None

    service.mark_used(resolved)
    assert resolved.last_used_at is not None


def test_resolve_returns_none_for_an_unknown_key(db):
    from modules.autocount.services.pull_key_service import KEY_SCHEME, PullKeyService

    assert PullKeyService(db).resolve(KEY_SCHEME + "totally-made-up") is None


def test_resolve_returns_none_for_a_malformed_or_wrong_scheme_key(db):
    from modules.autocount.services.pull_key_service import PullKeyService

    service = PullKeyService(db)
    assert service.resolve("") is None
    assert service.resolve("not-a-key-at-all") is None
    assert service.resolve("fxw_live_wrong_scheme_prefix") is None  # the OMNICHANNEL scheme


def test_resolve_returns_none_for_a_revoked_key(db):
    from modules.autocount.services.pull_key_service import PullKeyService

    service = PullKeyService(db)
    company = _company(db)
    key, plaintext = service.issue(DEFAULT_TENANT_ID, name="k", company_ids=[company.id])
    service.revoke(DEFAULT_TENANT_ID, key.id)

    assert service.resolve(plaintext) is None


def test_resolve_never_matches_a_similar_but_wrong_key_control(db):
    """CONTROL for the compare-digest path: a key sharing the SAME 8-char
    prefix (the indexed lookup column) but a different remainder must still
    miss - proves the match is on the full hash, not merely the prefix."""
    from modules.autocount.services.pull_key_service import PREFIX_LEN, PullKeyService

    service = PullKeyService(db)
    company = _company(db)
    key, plaintext = service.issue(DEFAULT_TENANT_ID, name="k", company_ids=[company.id])
    tampered = plaintext[: len(plaintext) - 1] + (
        "0" if plaintext[-1] != "0" else "1"
    )
    assert tampered != plaintext
    assert tampered[: len(plaintext) - PREFIX_LEN] == plaintext[: len(plaintext) - PREFIX_LEN]

    assert service.resolve(tampered) is None
    # POSITIVE control - the real key still resolves (the fixture itself is sound).
    assert service.resolve(plaintext) is not None


# ── AC-10-27/47: revoke + list are tenant-scoped ─────────────────────────────


def test_revoke_sets_revoked_at_and_is_idempotent(db):
    from modules.autocount.services.pull_key_service import PullKeyService

    service = PullKeyService(db)
    company = _company(db)
    key, _plaintext = service.issue(DEFAULT_TENANT_ID, name="k", company_ids=[company.id])

    revoked = service.revoke(DEFAULT_TENANT_ID, key.id)
    assert revoked.revoked_at is not None
    first_stamp = revoked.revoked_at

    revoked_again = service.revoke(DEFAULT_TENANT_ID, key.id)
    assert revoked_again.revoked_at == first_stamp


def test_revoke_on_another_tenants_key_raises_not_found(db):
    from modules.autocount.services.pull_key_service import (
        PullKeyNotFound,
        PullKeyService,
    )

    _other_tenant(db)
    service = PullKeyService(db)
    their_company = _company(db, OTHER_TENANT)
    theirs, _plaintext = service.issue(
        OTHER_TENANT, name="theirs", company_ids=[their_company.id]
    )

    with pytest.raises(PullKeyNotFound):
        service.revoke(DEFAULT_TENANT_ID, theirs.id)
    # CONTROL: the key itself is untouched by the refused cross-tenant call.
    from modules.autocount.models import AcPullApiKey

    db.refresh(theirs)
    assert theirs.revoked_at is None


def test_list_for_tenant_never_returns_another_tenants_keys(db):
    from modules.autocount.services.pull_key_service import PullKeyService

    _other_tenant(db)
    service = PullKeyService(db)
    mine_company = _company(db)
    their_company = _company(db, OTHER_TENANT)
    service.issue(DEFAULT_TENANT_ID, name="mine", company_ids=[mine_company.id])
    service.issue(OTHER_TENANT, name="theirs", company_ids=[their_company.id])

    mine = service.list_for_tenant(DEFAULT_TENANT_ID)
    assert [k.name for k in mine] == ["mine"]


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_resolve_never_matches_a_similar_but_wrong_key_control dies if the
#   coder matches on the prefix column ALONE (skipping `hmac.compare_digest`
#   on the full hash) - a real security regression this codebase has
#   specifically guarded against once already (omnichannel).
# * test_revoke_on_another_tenants_key_raises_not_found dies if `revoke`
#   resolves the key with an unscoped `get_by_id` (the polymorphic-id leak
#   class, AC-10-47) - the control assertion also catches a "silently
#   succeeds but on nobody's key" false negative.
# * test_resolve_returns_none_for_a_revoked_key dies if `resolve` forgets to
#   filter `revoked_at IS NULL` in its candidate query.
