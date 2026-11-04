"""Batched webhook routing, review round 2.

RED tests written BEFORE the fixes. Black box through
``InboundService.process_payload`` and the public web chat routes.
Pins: the service never regains an entry-less URL fallback; odd ``object``
values and unusable identifiers are handled; the URL channel is a fallback only
when it has no identifier of its own and is of the payload's type; template
events fan out to every live channel of their WABA and match by Meta template
id only; module checks are cached per tenant; non-object items inside a
``messages`` list never block siblings.

Every test seeds its own tenants, workspaces, channels, templates. Fake ids only.
"""
import itertools

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.models import Channel, ConversationMessage, WhatsappTemplate
from modules.omnichannel.services import inbound_service
from tests.test_omnichannel_inbound_batched_entries import (  # noqa: F401  (autouse fixture re-used)
    _channel,
    _change,
    _env,
    _in_msg,
    _msg_rows,
    _process,
    _sent_message,
    _status,
    _stored,
    _tenant,
    _wa,
    _workspace,
    _world,
)
from tests.test_omnichannel_inbound_routing_round1 import (
    _Counter,
    _counted,
    _page_entry,
    _page_payload,
    _tpl_status,
    _tpl_event,
)

_n = itertools.count(1)


def _ok(rows, tenant, channel):
    return [(t, c) for t, c, *_ in rows] == [(tenant, channel)]


def _raw_change(metadata, messages=None, statuses_=None):
    value = {"messaging_product": "whatsapp"}
    if metadata is not None:
        value["metadata"] = metadata
    if messages is not None:
        value["contacts"] = [{"wa_id": "60000000201", "profile": {"name": "Cust"}}]
        value["messages"] = messages
    if statuses_ is not None:
        value["statuses"] = statuses_
    return {"field": "messages", "value": value}


# ── 1. no entry-less fallback (guard) ────────────────────────────────────────
@pytest.mark.parametrize("shape", ["entryless", "meta_shaped_no_match"])
def test_entryless_or_unmatched_body_never_reaches_a_webchat_channel(session_factory, monkeypatch, shape):
    n = next(_n)
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    ch = _channel(session_factory, DEFAULT_TENANT_ID, ws, channel_type="WEBCHAT", account=f"wk-guard-{n}")
    reached = []
    real = inbound_service.get_adapter
    monkeypatch.setattr(inbound_service, "get_adapter", lambda t: reached.append(t) or real(t))
    ext = f"web:guard:{n}"
    if shape == "entryless":
        payload = {"from": "visitor:guard", "external_message_id": ext, "body": "hello"}
    else:
        payload = _wa([_raw_change({"phone_number_id": f"pn-none-{n}"}, messages=[_in_msg(ext, "60000000202")])])
    _process(session_factory, ch, payload)
    assert _msg_rows(session_factory, ext) == []
    assert "WEBCHAT" not in reached


# ── 2. odd `object` values never raise ───────────────────────────────────────
@pytest.mark.parametrize("obj", [["page"], {"k": "page"}, 5, None])
def test_odd_object_values_do_not_raise(session_factory, obj):
    n = next(_n)
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    ch = _channel(session_factory, DEFAULT_TENANT_ID, ws, pnid=f"pn-obj-{n}")
    payload = {"object": obj, "entry": [{"id": "x", "changes": [_change(f"pn-obj-{n}", messages=[_in_msg(f"wamid.o-{n}", "60000000203")])]}]}
    assert isinstance(_process(session_factory, ch, payload), dict)


# ── 3. unusable identifiers still name an identifier ─────────────────────────
@pytest.mark.parametrize("bad", [1.5, "", {}, []], ids=["float", "empty", "dict", "list"])
def test_unusable_phone_number_id_is_skipped_when_url_channel_owns_a_number(session_factory, bad):
    n = next(_n)
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    url_ch = _channel(session_factory, DEFAULT_TENANT_ID, ws, pnid=f"pn-own-r2-{n}")
    mid = f"wamid.bad-{n}"
    _process(session_factory, url_ch, _wa([_raw_change({"phone_number_id": bad}, messages=[_in_msg(mid, "60000000204")])]))
    assert _msg_rows(session_factory, mid) == []


@pytest.mark.parametrize("obj", ["page", "instagram"])
@pytest.mark.parametrize("bad", [1.5, "", {}, []], ids=["float", "empty", "dict", "list"])
def test_unusable_page_id_is_skipped_when_url_channel_owns_an_account(session_factory, obj, bad):
    n = next(_n)
    ctype = "FACEBOOK" if obj == "page" else "INSTAGRAM"
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    url_ch = _channel(session_factory, DEFAULT_TENANT_ID, ws, channel_type=ctype, account=f"acct-r2-{n}")
    mid = f"m.badpg-{n}"
    entry = _page_entry("x", "psid-bad", mid)
    entry["id"] = bad
    _process(session_factory, url_ch, _page_payload(obj, entry))
    assert _msg_rows(session_factory, mid) == []


# ── 4. missing metadata uses the URL channel only if it has no number ────────
@pytest.mark.parametrize("meta", [None, {}, {"display_phone_number": "x"}], ids=["absent", "empty", "no_number"])
def test_message_without_a_number_is_skipped_when_url_channel_owns_one(session_factory, meta):
    n = next(_n)
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    url_ch = _channel(session_factory, DEFAULT_TENANT_ID, ws, pnid=f"pn-own-r2b-{n}")
    mid = f"wamid.nm-{n}"
    _process(session_factory, url_ch, _wa([_raw_change(meta, messages=[_in_msg(mid, "60000000205")])]))
    assert _msg_rows(session_factory, mid) == []


@pytest.mark.parametrize("meta", [None, {}, {"display_phone_number": "x"}], ids=["absent", "empty", "no_number"])
def test_message_without_a_number_is_stored_when_url_channel_has_none(session_factory, meta):
    n = next(_n)
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    url_ch = _channel(session_factory, DEFAULT_TENANT_ID, ws, pnid=None)
    mid = f"wamid.nl-{n}"
    _process(session_factory, url_ch, _wa([_raw_change(meta, messages=[_in_msg(mid, "60000000206")])]))
    assert _ok(_msg_rows(session_factory, mid), DEFAULT_TENANT_ID, url_ch)


@pytest.mark.parametrize("meta", [None, {}], ids=["absent", "empty"])
def test_status_without_a_number_follows_the_same_rule(session_factory, meta):
    n = next(_n)
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    owned = _channel(session_factory, DEFAULT_TENANT_ID, ws, pnid=f"pn-own-r2c-{n}")
    free = _channel(session_factory, DEFAULT_TENANT_ID, ws, pnid=None)
    w1, w2 = f"wamid.st1-{n}", f"wamid.st2-{n}"
    _sent_message(session_factory, DEFAULT_TENANT_ID, ws, owned, w1, "60000000207")
    _sent_message(session_factory, DEFAULT_TENANT_ID, ws, free, w2, "60000000208")
    _process(session_factory, owned, _wa([_raw_change(meta, statuses_=[_status(w1)])]))
    _process(session_factory, free, _wa([_raw_change(meta, statuses_=[_status(w2)])]))
    assert _stored(session_factory, w1)[0][2] == "SENT"
    assert _stored(session_factory, w2)[0][2] == "DELIVERED"


# ── 5. web chat visitor message still honours the module-active check ────────
def test_webchat_visitor_message_not_stored_when_module_is_inactive(client, session_factory):
    from app.services.app_store_service import AppStoreService
    from tests.test_omnichannel_webchat_public import _new_channel, _post_message, _session

    widget_key, channel_id = _new_channel(client)
    token = _session(client, widget_key).json()["token"]
    assert _post_message(client, widget_key, token, text="while active").status_code == 201
    db = session_factory()
    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
    db.commit()
    db.close()
    try:
        _post_message(client, widget_key, token, text="while inactive")
    finally:
        db2 = session_factory()
        AppStoreService(db2).reactivate(DEFAULT_TENANT_ID, "omnichannel")
        db2.commit()
        db2.close()
    db = session_factory()
    try:
        bodies = [m.body for m in db.query(ConversationMessage).filter(ConversationMessage.channel_id == channel_id)]
    finally:
        db.close()
    assert bodies == ["while active"]


# ── 6. type filter on the URL fallback ───────────────────────────────────────
def test_instagram_payload_is_not_stored_on_a_facebook_url_channel(session_factory):
    n = next(_n)
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    url_ch = _channel(session_factory, DEFAULT_TENANT_ID, ws, channel_type="FACEBOOK", account=None)
    mid = f"m.xt-{n}"
    _process(session_factory, url_ch, _page_payload("instagram", _page_entry(f"ig-elsewhere-{n}", "igsid-x", mid)))
    assert _msg_rows(session_factory, mid) == []


# ── 7/8/9. template events ───────────────────────────────────────────────────
def _tpl_channel(session_factory, tenant, ws, waba, *, meta_id, name="order_update", trashed=False, pnid=None):
    ch = _channel(session_factory, tenant, ws, pnid=pnid or f"pn-t-{next(_n)}")
    db = session_factory()
    db.query(Channel).filter(Channel.id == ch).update({"waba_id": waba, "is_trashed": trashed})
    row = WhatsappTemplate(tenant_id=tenant, channel_id=ch, name=name, language="en_US",
                           status="PENDING", meta_template_id=meta_id)
    db.add(row)
    db.flush()
    rid = row.id
    db.commit()
    db.close()
    return ch, rid


def _event_with_id(waba, meta_id, status="REJECTED"):
    payload = _tpl_event(waba, status)
    payload["entry"][0]["changes"][0]["value"]["message_template_id"] = meta_id
    return payload


def test_template_event_updates_every_live_channel_of_the_waba(session_factory):
    n = next(_n)
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    waba, mid = f"waba-fan-{n}", f"meta-fan-{n}"
    c1, t1 = _tpl_channel(session_factory, DEFAULT_TENANT_ID, ws, waba, meta_id=mid)
    c2, t2 = _tpl_channel(session_factory, DEFAULT_TENANT_ID, ws, waba, meta_id=mid)
    _process(session_factory, c1, _event_with_id(waba, mid))
    assert _tpl_status(session_factory, t1) == "REJECTED"
    assert _tpl_status(session_factory, t2) == "REJECTED"


def test_template_event_does_not_touch_a_trashed_channels_template(session_factory):
    n = next(_n)
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    waba, mid = f"waba-tr-{n}", f"meta-tr-{n}"
    live, t_live = _tpl_channel(session_factory, DEFAULT_TENANT_ID, ws, waba, meta_id=mid)
    _gone, t_gone = _tpl_channel(session_factory, DEFAULT_TENANT_ID, ws, waba, meta_id=mid, trashed=True)
    _process(session_factory, live, _event_with_id(waba, mid))
    assert _tpl_status(session_factory, t_live) == "REJECTED"
    assert _tpl_status(session_factory, t_gone) == "PENDING"


def test_template_event_name_match_applies_to_a_row_without_a_meta_id(session_factory):
    n = next(_n)
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    waba, mid = f"waba-legacy-{n}", f"meta-legacy-{n}"
    ch, legacy = _tpl_channel(session_factory, DEFAULT_TENANT_ID, ws, waba, meta_id=None)
    _process(session_factory, ch, _event_with_id(waba, mid))
    assert _tpl_status(session_factory, legacy) == "REJECTED"


def test_template_event_never_name_matches_a_row_with_a_different_meta_id(session_factory):
    n = next(_n)
    t2 = _tenant(session_factory, f"r2-t2-{n}")
    ws1 = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    ws2 = _workspace(session_factory, t2, default=True)
    waba, mid = f"waba-id-{n}", f"meta-id-{n}"
    c1, tpl1 = _tpl_channel(session_factory, DEFAULT_TENANT_ID, ws1, waba, meta_id=mid)
    _c2, tpl2 = _tpl_channel(session_factory, t2, ws2, waba, meta_id="meta-other")
    c3, tpl3 = _tpl_channel(session_factory, DEFAULT_TENANT_ID, ws1, f"waba-id3-{n}", meta_id="meta-other-3")
    _process(session_factory, c1, _event_with_id(waba, mid))
    assert _tpl_status(session_factory, tpl1) == "REJECTED"
    assert _tpl_status(session_factory, tpl2) == "PENDING"
    # same channel, same name, different Meta id: also untouched
    _process(session_factory, c3, _event_with_id(f"waba-id3-{n}", f"meta-unrelated-{n}"))
    assert _tpl_status(session_factory, tpl3) == "PENDING"


# ── 10. module-active checks cached per tenant ───────────────────────────────
def test_module_checks_do_not_grow_with_parts_across_two_tenants(session_factory):
    w = _world(session_factory, two_tenants=True)

    def payload(count, tag):
        changes = []
        for i in range(count):
            for pn in (w["pa"], w["pb"]):
                changes.append(_change(pn, messages=[_in_msg(f"wamid.mc-{tag}-{pn}-{i}", "60000000211")]))
        return _wa(changes)

    small = _counted(session_factory, w["ch_a"], payload(3, "s"))
    large = _counted(session_factory, w["ch_a"], payload(20, "l"))
    assert large[1] <= 2, large
    assert small[1] <= 2, small


# ── 11. non-object items inside `messages` ───────────────────────────────────
@pytest.mark.parametrize("junk", ["junk", 7, None, ["x"]], ids=["str", "int", "none", "list"])
def test_non_object_message_items_do_not_block_siblings(session_factory, junk):
    w = _world(session_factory, two_tenants=False)
    ok = f"wamid.junk-{w['n']}"
    bad = _raw_change({"phone_number_id": w["pa"]}, messages=[junk])
    good = _change(w["pb"], messages=[_in_msg(ok, "60000000212")])
    assert isinstance(_process(session_factory, w["ch_a"], _wa([bad, good])), dict)
    assert _ok(_msg_rows(session_factory, ok), w["t1"], w["ch_b"])
