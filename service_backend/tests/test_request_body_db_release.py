"""Routes that wait for a request body start no database work until it has arrived.

Rule (storage-and-background-jobs.md): never hold an app-DB read transaction across
a wait. Five `async def` routes take a request body; the body is read first, so no
statement has run and no session holds a transaction while the route waits for it.
Sign-in is checked by token signature only until the body is in:

  1. connector   POST /mcp/{p}/oauth/token                   (form body)
  2. forms       POST /forms/{id}/submissions                (JSON and multipart)
  3. forms       POST /submissions/{id}/resubmit             (JSON and multipart)
  4. omnichannel POST /omnichannel/contacts/{id}/template    (JSON and multipart)
  5. omnichannel POST /omnichannel/contacts/{id}/interactive (JSON and multipart)

The ASGI app is driven directly with a `receive` callable that blocks until the test
releases the body, so the wait is real whatever a client transport buffers.
Statements are counted at engine level. The in-memory suite cannot see pool
behaviour, so nothing here counts connections: it asserts on session state and on
statements.

Existing suites that already pin the answers of these routes:
  route 1  test_connector_oauth.py        success, unsupported grant, refusals
  route 2  test_form_engine.py            success, 422 fieldErrors, 409 closed
           test_form_uploads.py           multipart success, bad-file 422
  route 3  test_form_revisions.py         success, 422 fieldErrors
  route 4  test_omnichannel_rich_messages.py  JSON + multipart success, 422 counts
           test_omnichannel_embed.py      read-only token refused
  route 5  test_omnichannel_rich_messages.py  JSON + multipart success, 422 limits
This file adds only what those do not pin.
"""
import asyncio
import gc
import json
import os
import tempfile
import uuid
import weakref
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import httpx
import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.main import app
from tests.connector_support import REDIRECT, get_code
from tests.test_form_revisions import _admin as _forms_admin
from tests.test_form_revisions import _published_form, _submit
from tests.test_form_uploads import _PNG, _doc as _file_doc, _publish
from tests.test_omnichannel_rich_messages import (
    PNG,
    _MEDIA_HEADER,
    _auth,
    _default_workspace_id,
    _seed_channel,
    _seed_contact,
    _seed_template,
)

BOUND = 60.0  # only a real hang reaches this; every wait returns as soon as its event fires


@pytest.fixture(autouse=True)
def _tmp_media(tmp_path):
    from app.config import settings
    from app.services.storage import set_storage

    prev = settings.media_root
    settings.media_root = str(tmp_path)
    set_storage(None)
    yield
    settings.media_root = prev
    set_storage(None)


@pytest.fixture
def tracker():
    seen = weakref.WeakSet()

    def track(session, transaction, connection):
        seen.add(session)

    event.listen(Session, "after_begin", track)
    try:
        yield lambda: [s for s in list(seen) if s.in_transaction()]
    finally:
        event.remove(Session, "after_begin", track)


class Spies:
    """Records the label of every call of the wrapped functions, then calls through
    to the real one."""

    def __init__(self, monkeypatch):
        self._mp = monkeypatch
        self.calls: List[str] = []

    def watch(self, label: str, targets: List[Tuple[Any, str]]) -> None:
        original = getattr(targets[0][0], targets[0][1])
        calls = self.calls

        def wrapper(*args, **kwargs):
            calls.append(label)
            return original(*args, **kwargs)

        for owner, attr in targets:
            self._mp.setattr(owner, attr, wrapper)

    def labels(self) -> List[str]:
        return list(self.calls)


@pytest.fixture
def spies(monkeypatch):
    return Spies(monkeypatch)


# ── the driver ───────────────────────────────────────────────────────────────
@dataclass
class Run:
    receive_calls: int = 0
    sampled: Optional[int] = None
    status: Optional[int] = None
    headers: Dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def json(self) -> Any:
        return json.loads(self.body)


async def _drive(scn: "Scenario", *, hold: bool, sample: Optional[Callable[[], int]] = None,
                 headers: Optional[Dict[str, str]] = None, path: Optional[str] = None,
                 length: Any = "auto", chunk: Optional[int] = None,
                 disconnect: bool = False, ctype: Any = "auto", strict: bool = True,
                 leave_after: Optional[int] = None) -> Run:
    """POST the scenario straight into the ASGI app. With `hold` the body is withheld
    until the app asks for it (so every dependency and pre-check has finished) and
    `sample()` is taken at that moment; without it the body is available at once and
    the run simply records whether the app ever asked for it."""
    run = Run()
    release = asyncio.Event()
    if not hold:
        release.set()
    first_receive = asyncio.Event()
    sent: List[int] = []

    async def receive():
        run.receive_calls += 1
        first_receive.set()
        await release.wait()
        if disconnect or (leave_after is not None and len(sent) >= leave_after):
            return {"type": "http.disconnect"}
        if sent and (chunk is None or len(sent) * chunk >= len(scn.body)):
            if hold:
                await asyncio.Event().wait()  # no disconnect during the test
            return {"type": "http.disconnect"}
        if chunk is None:
            sent.append(1)
            return {"type": "http.request", "body": scn.body, "more_body": False}
        start = len(sent) * chunk
        piece = scn.body[start:start + chunk]
        sent.append(1)
        return {"type": "http.request", "body": piece, "more_body": start + chunk < len(scn.body)}

    async def send(message):
        if message["type"] == "http.response.start":
            run.status = message["status"]
            run.headers = {k.decode().lower(): v.decode() for k, v in message["headers"]}
        elif message["type"] == "http.response.body":
            run.body += message.get("body", b"")

    use_path = path or scn.path
    raw_headers = [
        (b"host", b"testserver"),
    ]
    if ctype == "auto":
        raw_headers.append((b"content-type", scn.content_type.encode()))
    elif ctype is not None:
        raw_headers.append((b"content-type", ctype.encode()))
    if length == "auto":
        raw_headers.append((b"content-length", str(len(scn.body)).encode()))
    elif length is not None and length != "omit":
        raw_headers.append((b"content-length", str(length).encode()))
    merged = dict(scn.headers if headers is None else headers)
    raw_headers += [(k.lower().encode(), v.encode()) for k, v in merged.items()]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": scn.scheme,
        "path": use_path,
        "raw_path": use_path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": raw_headers,
        "client": ("testclient", 5000),
        "server": ("testserver", 443 if scn.scheme == "https" else 80),
    }
    task = asyncio.create_task(app(scope, receive, send))
    try:
        if hold:
            waiter = asyncio.ensure_future(first_receive.wait())
            await asyncio.wait({waiter, task}, timeout=BOUND, return_when=asyncio.FIRST_COMPLETED)
            waiter.cancel()
            if strict or first_receive.is_set():
                assert first_receive.is_set(), "the app never asked for the request body"
                assert not task.done(), "the request ended before the body was released"
                run.sampled = sample() if sample else None
            release.set()
        await asyncio.wait_for(task, BOUND)
    finally:
        release.set()
        if not task.done():
            task.cancel()
    return run


def _multipart(data: Optional[dict] = None, files: Any = None) -> Tuple[bytes, str]:
    req = httpx.Request("POST", "http://testserver/", data=data, files=files)
    return req.read(), req.headers["content-type"]


@dataclass
class Scenario:
    name: str
    path: str
    headers: Dict[str, str]
    body: bytes
    content_type: str
    status: int
    watch: List[Tuple[str, List[Tuple[Any, str]]]]
    expect: List[str]
    check: Callable[[Run], None]
    scheme: str = "http"
    ctx: Dict[str, Any] = field(default_factory=dict)


# ── scenario builders (each seeds its own data chain) ───────────────────────
def _token_scenario(request, *, bad_grant: bool) -> Scenario:
    from app.services.throttle import ThrottleService
    from modules.connector.services.oauth_service import OAuthService

    c = request.getfixturevalue("connector_client")
    g = get_code(c)
    form = {
        "grant_type": "authorization_code",
        "code": g["code"],
        "code_verifier": ("z" * 50) if bad_grant else g["verifier"],
        "client_id": g["client_id"],
        "redirect_uri": REDIRECT,
    }
    watch = [
        ("enforce_connector", [(ThrottleService, "enforce_connector")]),
        ("token", [(OAuthService, "token")]),
        ("record_connector", [(ThrottleService, "record_connector")]),
    ]
    if bad_grant:
        def check(run: Run) -> None:
            assert run.json() == {"error": "invalid_grant"}
        return Scenario("token_bad_grant", "/mcp/acme/oauth/token", {}, urlencode(form).encode(),
                        "application/x-www-form-urlencoded", 400, watch,
                        ["enforce_connector", "token", "record_connector"], check, scheme="https")

    def check(run: Run) -> None:
        body = run.json()
        assert body["access_token"] and body["refresh_token"]
        assert run.headers.get("cache-control") == "no-store"
    return Scenario("token_form", "/mcp/acme/oauth/token", {}, urlencode(form).encode(),
                    "application/x-www-form-urlencoded", 200, watch,
                    ["enforce_connector", "token"], check, scheme="https")


def _forms_watch(*, with_perms: bool) -> List[Tuple[str, List[Tuple[Any, str]]]]:
    from app.api.v1 import forms as forms_router
    from app.services.form_service import FormService

    watch: List[Tuple[str, List[Tuple[Any, str]]]] = [
        ("get_submission", [(FormService, "get_submission")]),
    ]
    if with_perms:
        watch += [
            ("resubmit_revision", [(FormService, "resubmit_revision")]),
            ("effective_permission_keys", [(forms_router, "effective_permission_keys")]),
        ]
    else:
        watch += [("submit", [(FormService, "submit")])]
    return watch


def _submit_scenario(request, *, multipart: bool) -> Scenario:
    client = request.getfixturevalue("client")
    headers = _forms_admin(client)
    expect = ["submit", "get_submission"]
    if multipart:
        form = _publish(client, headers, _file_doc(
            {"id": "f1", "type": "file", "key": "resume", "label": "Resume", "required": True},
        ))
        body, ctype = _multipart(
            data={"payload": json.dumps({"answers": {}})},
            files=[("file:resume", ("cv.png", _PNG, "image/png"))],
        )

        def check(run: Run) -> None:
            resume = run.json()["answers"]["resume"]
            assert isinstance(resume, list) and len(resume) == 1
        name = "submit_multipart"
    else:
        form = _published_form(client, headers)
        body, ctype = json.dumps({"answers": {"name": "Alice"}}).encode(), "application/json"

        def check(run: Run) -> None:
            assert run.json()["answers"] == {"name": "Alice"}
        name = "submit_json"
    return Scenario(name, f"/forms/{form['id']}/submissions", dict(headers), body, ctype, 201,
                    _forms_watch(with_perms=False), expect, check)


def _resubmit_scenario(request, *, multipart: bool) -> Scenario:
    client = request.getfixturevalue("client")
    headers = _forms_admin(client)
    form = _published_form(client, headers)
    original = _submit(client, headers, form["id"], {"name": "Alice"})
    draft = client.post(f"/submissions/{original['id']}/revise", headers=headers).json()
    answers = {"answers": {"name": "Alice Revised"}}
    if multipart:
        body, ctype = _multipart(files={"payload": (None, json.dumps(answers))})
        name = "resubmit_multipart"
    else:
        body, ctype = json.dumps(answers).encode(), "application/json"
        name = "resubmit_json"

    def check(run: Run) -> None:
        out = run.json()
        assert out["id"] == draft["id"]
        assert out["answers"] == {"name": "Alice Revised"}
        assert out["statusKey"] == "submitted"
    return Scenario(name, f"/submissions/{draft['id']}/resubmit", dict(headers), body, ctype, 200,
                    _forms_watch(with_perms=True),
                    ["resubmit_revision", "get_submission", "effective_permission_keys"], check)


def _thread_watch(send_attr: str) -> List[Tuple[str, List[Tuple[Any, str]]]]:
    from modules.omnichannel import embed_auth
    from modules.omnichannel.routers import conversations as conv_router
    from modules.omnichannel.services.message_service import MessageService

    return [
        ("enforce_thread_access", [
            (conv_router, "enforce_thread_access"),
            (embed_auth, "enforce_thread_access"),
        ]),
        (send_attr, [(MessageService, send_attr)]),
    ]


def _inbox_headers(client, sf, ws) -> Dict[str, str]:
    """A bearer for an inbox-scoped embed token: the one caller whose thread
    pre-check has to look the conversation up in the database."""
    from tests.test_omnichannel_embed import _assertion, _bearer, _exchange, _make_connection

    connection = _make_connection(sf)
    token = _exchange(client, _assertion(iss=connection, workspace_id=ws, scope="inbox")).json()["accessToken"]
    return _bearer(token)


def _lookup_watch() -> List[Tuple[str, List[Tuple[Any, str]]]]:
    from modules.omnichannel.repositories.contact_repository import ContactRepository

    return [("contact_lookup", [(ContactRepository, "get_by_id")])]


def _omni_setup(request, *, phone_number_id: str):
    client = request.getfixturevalue("client")
    sf = request.getfixturevalue("session_factory")
    ws = _default_workspace_id(sf)
    ch = _seed_channel(sf, ws, phone_number_id=phone_number_id)
    cid = _seed_contact(sf, ws, phone="+60190000001")
    return client, sf, ws, ch, cid


def _template_scenario(request, *, multipart: bool, inbox: bool = False) -> Scenario:
    client, sf, ws, ch, cid = _omni_setup(request, phone_number_id="pn-body-tpl")
    headers = _inbox_headers(client, sf, ws) if inbox else _auth(client)
    if multipart:
        tid = _seed_template(sf, ch, _MEDIA_HEADER, name="flyer_promo")
        body, ctype = _multipart(
            data={"payload": json.dumps({"templateId": tid, "templateVariables": ["Sarah"]})},
            files={"file": ("flyer.png", PNG, "image/png")},
        )
        name = "template_multipart"
    else:
        tid = _seed_template(sf, ch, [{"type": "BODY", "text": "Hi {{1}}, thanks!"}], name="plain_body")
        body = json.dumps({"templateId": tid, "templateVariables": ["Sarah"]}).encode()
        ctype, name = "application/json", "template_json"
    if inbox:
        name = name.replace("template_", "template_inbox_")

    def check(run: Run) -> None:
        out = run.json()
        assert out["messageType"] == "TEMPLATE"
        assert out["deliveryStatus"] == "SENT"
    return Scenario(name, f"/omnichannel/contacts/{cid}/template", dict(headers), body, ctype, 201,
                    _thread_watch("send_message") + (_lookup_watch() if inbox else []),
                    ["enforce_thread_access", "send_message"] + (["contact_lookup"] if inbox else []), check,
                    ctx={"sf": sf, "ws": ws, "cid": cid, "client": client})


def _interactive_scenario(request, *, multipart: bool, inbox: bool = False) -> Scenario:
    client, sf, ws, _ch, cid = _omni_setup(request, phone_number_id="pn-body-int")
    headers = _inbox_headers(client, sf, ws) if inbox else _auth(client)
    defn = {"kind": "buttons", "body": "Pick one",
            "buttons": [{"id": "y", "title": "Yes"}, {"id": "n", "title": "No"}]}
    if multipart:
        defn = {**defn, "header": {"type": "image"}}
        body, ctype = _multipart(
            data={"payload": json.dumps(defn)}, files={"file": ("h.png", PNG, "image/png")}
        )
        name = "interactive_multipart"
    else:
        body, ctype, name = json.dumps(defn).encode(), "application/json", "interactive_json"
    if inbox:
        name = name.replace("interactive_", "interactive_inbox_")

    def check(run: Run) -> None:
        out = run.json()
        assert out["messageType"] == "INTERACTIVE"
        assert out["deliveryStatus"] == "SENT"
    return Scenario(name, f"/omnichannel/contacts/{cid}/interactive", dict(headers), body, ctype, 201,
                    _thread_watch("send_interactive") + (_lookup_watch() if inbox else []),
                    ["enforce_thread_access", "send_interactive"] + (["contact_lookup"] if inbox else []), check,
                    ctx={"sf": sf, "ws": ws, "cid": cid, "client": client})


BUILDERS: Dict[str, Callable[[Any], Scenario]] = {
    "token_form": lambda r: _token_scenario(r, bad_grant=False),
    "token_bad_grant": lambda r: _token_scenario(r, bad_grant=True),
    "submit_json": lambda r: _submit_scenario(r, multipart=False),
    "submit_multipart": lambda r: _submit_scenario(r, multipart=True),
    "resubmit_json": lambda r: _resubmit_scenario(r, multipart=False),
    "resubmit_multipart": lambda r: _resubmit_scenario(r, multipart=True),
    "template_json": lambda r: _template_scenario(r, multipart=False),
    "template_multipart": lambda r: _template_scenario(r, multipart=True),
    "interactive_json": lambda r: _interactive_scenario(r, multipart=False),
    "interactive_multipart": lambda r: _interactive_scenario(r, multipart=True),
    "template_inbox_json": lambda r: _template_scenario(r, multipart=False, inbox=True),
    "template_inbox_multipart": lambda r: _template_scenario(r, multipart=True, inbox=True),
    "interactive_inbox_json": lambda r: _interactive_scenario(r, multipart=False, inbox=True),
    "interactive_inbox_multipart": lambda r: _interactive_scenario(r, multipart=True, inbox=True),
}
SCENARIOS = list(BUILDERS)
SIGNED_IN_SCENARIOS = [n for n in SCENARIOS if not n.startswith("token")]
CONVERSATION_SCENARIOS = [n for n in SCENARIOS if n.startswith(("template", "interactive")) and "inbox" not in n]


@pytest.fixture
def scenario(request):
    return BUILDERS[request.param](request)


def _arm(scn: Scenario, spies: Spies) -> None:
    for label, targets in scn.watch:
        spies.watch(label, targets)


def _run_held(scn: Scenario, tracker) -> Run:
    return asyncio.run(_drive(scn, hold=True, sample=lambda: len(tracker())))


# ── harness control ──────────────────────────────────────────────────────────
def test_tracker_control_sees_open_and_closed(session_factory, tracker):
    probe = session_factory()
    probe.execute(text("select 1"))
    assert len(tracker()) == 1
    probe.close()
    assert tracker() == []


# ── no transaction is open while the route waits for its body ───────────────
@pytest.mark.parametrize("scenario", SCENARIOS, indirect=True)
def test_no_transaction_is_open_while_the_route_waits_for_its_body(scenario, tracker):
    run = _run_held(scenario, tracker)
    assert run.sampled == 0, f"{run.sampled} session(s) held a transaction while the body was pending"
    assert run.status == scenario.status, run.body


# ── A1: no statement has run by the time the route first waits for its body ─
@pytest.mark.parametrize("scenario", SCENARIOS, indirect=True)
def test_no_statement_runs_before_the_body_arrives(scenario, sql_log):
    sql_log.clear()  # only the request itself is of interest, not the scenario setup
    before_body: List[str] = []

    def sample() -> int:
        before_body.extend(statement for statement in sql_log)
        return len(before_body)

    run = asyncio.run(_drive(scenario, hold=True, sample=sample))
    assert not before_body, (
        f"{len(before_body)} statement(s) ran before the body was requested, first: {before_body[0]!r}"
    )
    assert run.status == scenario.status, run.body


# ═════════════════════════════════════════════════════════════════════════════
# Answers that must not change, and what is refused before the body
# ═════════════════════════════════════════════════════════════════════════════


# ── sign-in problems answer 401 before the body is requested ───────────────
@pytest.mark.parametrize("scenario", CONVERSATION_SCENARIOS, indirect=True)
def test_a_token_without_access_to_the_thread_is_refused(scenario):
    from tests.test_omnichannel_embed import _assertion, _bearer, _exchange, _make_connection

    ctx = scenario.ctx
    other = _seed_contact(ctx["sf"], ctx["ws"], phone="+60190000002")
    connection = _make_connection(ctx["sf"])
    token = _exchange(
        ctx["client"],
        _assertion(iss=connection, workspace_id=ctx["ws"], scope=f"thread:{other}"),
    ).json()["accessToken"]
    run = asyncio.run(_drive(scenario, hold=False, headers=_bearer(token)))
    assert run.status == 403, run.body


def test_a_throttled_client_is_refused_on_the_token_route(connector_client):
    from app.config import settings
    from app.services.throttle import Throttled, ThrottleService

    scn = _token_scenario_for(connector_client)
    db = connector_client._factory()
    try:
        throttle = ThrottleService(db)
        for _ in range(settings.throttle_connector_max_fails):
            throttle.record_connector(key="tok:testclient")
        with pytest.raises(Throttled):  # control: the bucket really is full
            throttle.enforce_connector(key="tok:testclient")
    finally:
        db.close()
    run = asyncio.run(_drive(scn, hold=False))
    assert run.status == 429, run.body
    assert int(run.headers["retry-after"]) > 0
    assert run.headers["cache-control"] == "no-store"
    assert run.headers["pragma"] == "no-cache"
    assert run.json() == {"error": "too_many_requests"}


def _token_scenario_for(connector_client) -> Scenario:
    form = {"grant_type": "authorization_code", "code": "c", "code_verifier": "v" * 50,
            "client_id": "x", "redirect_uri": REDIRECT}
    return Scenario("token_throttled", "/mcp/acme/oauth/token", {}, urlencode(form).encode(),
                    "application/x-www-form-urlencoded", 429, [], [], lambda run: None, scheme="https")


_PLAIN_CONVERSATION = ["template_json", "template_multipart", "interactive_json", "interactive_multipart"]


@pytest.mark.parametrize("scenario", _PLAIN_CONVERSATION, indirect=True)
@pytest.mark.parametrize("caller", ["user_without_reply", "token_without_capability"])
def test_a_caller_without_the_send_permission_is_refused(scenario, caller):
    from tests.connector_support import seed_user_with_perms
    from tests.test_form_revisions import _login
    from tests.test_omnichannel_embed import _assertion, _bearer, _exchange, _make_connection

    ctx = scenario.ctx
    if caller == "user_without_reply":
        seed_user_with_perms(ctx["sf"], "reader@example.com", [])
        headers = _login(ctx["client"], "reader@example.com", "Passw0rd!x")
    else:
        connection = _make_connection(ctx["sf"])
        token = _exchange(ctx["client"], _assertion(
            iss=connection, workspace_id=ctx["ws"], scope="inbox", caps=("note",))).json()["accessToken"]
        headers = _bearer(token)
    run = asyncio.run(_drive(scenario, hold=False, headers=headers))
    assert run.status == 403, run.body


def test_the_inbox_scoped_thread_check_reads_the_database(session_factory, sql_log):
    from modules.omnichannel.embed_auth import ConversationPrincipal, enforce_thread_access
    from app.models import DEFAULT_TENANT_ID

    ws = _default_workspace_id(session_factory)
    cid = _seed_contact(session_factory, ws)
    principal = ConversationPrincipal(tenant_id=DEFAULT_TENANT_ID, is_embed=True, workspace_id=ws, scope="inbox")
    db = session_factory()
    try:
        sql_log.clear()
        enforce_thread_access(db, principal, cid)
        assert any(s.startswith("SELECT") for s in sql_log), "the inbox-scoped check issued no query"
        assert db.in_transaction()
    finally:
        db.close()


# ── the real flow: every route still answers correctly once the body arrives ─
@pytest.mark.parametrize("scenario", SCENARIOS, indirect=True)
def test_the_route_answers_correctly_once_the_body_arrives(scenario, spies, tracker):
    _arm(scenario, spies)
    run = _run_held(scenario, tracker)
    assert run.receive_calls >= 1
    assert run.status == scenario.status, run.body
    scenario.check(run)
    for label in scenario.expect:  # the work behind the answer really happened
        assert label in spies.labels(), f"{label} was never called"


# ── token route answers (gaps in test_connector_oauth.py) ───────────────────
def test_a_bad_grant_is_refused_and_counted_once(connector_client, spies):
    from app.services.throttle import ThrottleService

    spies.watch("record_connector", [(ThrottleService, "record_connector")])
    res = connector_client.post("/mcp/acme/oauth/token", data={
        "grant_type": "authorization_code", "code": "nope", "code_verifier": "v" * 50,
        "client_id": "nope", "redirect_uri": REDIRECT})
    assert res.status_code == 400
    assert res.json() == {"error": "invalid_grant"}
    assert res.headers["cache-control"] == "no-store"
    assert spies.labels().count("record_connector") == 1


def test_a_malformed_token_body_is_treated_as_an_empty_form(connector_client, spies):
    from app.services.throttle import ThrottleService

    spies.watch("record_connector", [(ThrottleService, "record_connector")])
    res = connector_client.post(
        "/mcp/acme/oauth/token", content=b"--garbage--",
        headers={"content-type": "multipart/form-data; boundary=missing"})
    assert res.status_code == 400
    assert res.json() == {"error": "unsupported_grant_type"}
    assert spies.labels().count("record_connector") == 1


# ── form submit and resubmit answers (gaps in test_form_*.py) ───────────────
def test_submit_to_an_unknown_form_is_404(client):
    headers = _forms_admin(client)
    res = client.post("/forms/no-such-form/submissions", json={"answers": {}}, headers=headers)
    assert res.status_code == 404


@pytest.mark.parametrize("body", [b"{not json", b"[1, 2]", b"\"text\""])
def test_submit_with_a_malformed_json_body_is_422(client, body):
    headers = _forms_admin(client)
    form = _published_form(client, headers)
    res = client.post(f"/forms/{form['id']}/submissions", content=body,
                      headers={**headers, "content-type": "application/json"})
    assert res.status_code == 422
    assert res.json()["detail"] == "Malformed request body."


def test_submit_with_a_malformed_multipart_payload_is_422(client):
    headers = _forms_admin(client)
    form = _published_form(client, headers)
    res = client.post(f"/forms/{form['id']}/submissions",
                      files={"payload": (None, "{not json")}, headers=headers)
    assert res.status_code == 422
    assert res.json()["detail"] == "Malformed submission payload."


def test_submit_with_an_oversize_file_is_413(client, monkeypatch):
    from app.config import settings

    headers = _forms_admin(client)
    form = _publish(client, headers, _file_doc(
        {"id": "f1", "type": "file", "key": "resume", "label": "Resume", "required": True}))
    monkeypatch.setattr(settings, "form_upload_max_file_mb", 0.001)  # about 1 KB
    res = client.post(
        f"/forms/{form['id']}/submissions",
        data={"payload": json.dumps({"answers": {}})},
        files=[("file:resume", ("big.png", _PNG + b"\x00" * 4096, "image/png"))],
        headers=headers,
    )
    assert res.status_code == 413
    assert res.json()["detail"] == "A file is too large."


def test_submit_json_with_a_honeypot_field_is_still_parsed(client):
    headers = _forms_admin(client)
    form = _published_form(client, headers)
    res = client.post(f"/forms/{form['id']}/submissions",
                      json={"answers": {"name": "Alice"}, "honeypot": "filled"}, headers=headers)
    assert res.status_code == 201, res.text
    assert res.json()["answers"] == {"name": "Alice"}


def test_submit_to_a_form_that_is_not_open_is_409(client):
    headers = _forms_admin(client)
    form = _published_form(client, headers)
    assert client.patch(f"/forms/{form['id']}", json={"maxSubmissions": 1}, headers=headers).status_code == 200
    assert client.post(f"/forms/{form['id']}/submissions", json={"answers": {"name": "A"}},
                       headers=headers).status_code == 201
    res = client.post(f"/forms/{form['id']}/submissions", json={"answers": {"name": "B"}}, headers=headers)
    assert res.status_code == 409


def test_resubmit_of_an_unknown_submission_is_404(client):
    headers = _forms_admin(client)
    res = client.post("/submissions/no-such-submission/resubmit", json={"answers": {}}, headers=headers)
    assert res.status_code == 404


def test_resubmit_by_someone_who_does_not_own_it_is_403(client, session_factory):
    from tests.connector_support import seed_user_with_perms
    from tests.test_form_revisions import _login

    headers = _forms_admin(client)
    form = _published_form(client, headers)
    original = _submit(client, headers, form["id"], {"name": "Alice"})
    draft = client.post(f"/submissions/{original['id']}/revise", headers=headers).json()
    seed_user_with_perms(session_factory, "bystander@example.com", [])
    other = _login(client, "bystander@example.com", "Passw0rd!x")
    res = client.post(f"/submissions/{draft['id']}/resubmit",
                      json={"answers": {"name": "Mallory"}}, headers=other)
    assert res.status_code == 403
    # control: the owner can edit the same draft
    ok = client.post(f"/submissions/{draft['id']}/resubmit",
                     json={"answers": {"name": "Alice 2"}}, headers=headers)
    assert ok.status_code == 200, ok.text


@pytest.mark.parametrize("body", [b"{not json", b"[1]"])
def test_resubmit_with_a_malformed_json_body_is_422(client, body):
    headers = _forms_admin(client)
    form = _published_form(client, headers)
    original = _submit(client, headers, form["id"], {"name": "Alice"})
    draft = client.post(f"/submissions/{original['id']}/revise", headers=headers).json()
    res = client.post(f"/submissions/{draft['id']}/resubmit", content=body,
                      headers={**headers, "content-type": "application/json"})
    assert res.status_code == 422


# ── conversation template and interactive answers ───────────────────────────
@pytest.mark.parametrize("route,body", [
    ("template", {"templateId": "x"}),
    ("interactive", {"kind": "buttons", "body": "b", "buttons": [{"id": "a", "title": "A"}]}),
])
def test_send_to_an_unknown_conversation_is_404(client, session_factory, route, body):
    _seed_channel(session_factory, _default_workspace_id(session_factory))
    res = client.post(f"/omnichannel/contacts/no-such-contact/{route}", json=body, headers=_auth(client))
    assert res.status_code == 404
    assert res.json()["detail"] == "Conversation not found"


@pytest.mark.parametrize("route", ["template", "interactive"])
def test_a_multipart_send_without_a_payload_part_is_422(client, session_factory, route):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    res = client.post(f"/omnichannel/contacts/{cid}/{route}",
                      files={"file": ("a.png", PNG, "image/png")}, headers=_auth(client))
    assert res.status_code == 422
    assert res.json()["detail"] == "A payload part is required."


@pytest.mark.parametrize("route", ["template", "interactive"])
def test_a_multipart_send_with_bad_payload_json_is_422(client, session_factory, route):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    res = client.post(f"/omnichannel/contacts/{cid}/{route}",
                      files={"payload": (None, "{not json")}, headers=_auth(client))
    assert res.status_code == 422
    assert res.json()["detail"] == "payload must be valid JSON."


@pytest.mark.parametrize("route", ["template", "interactive"])
def test_a_json_send_with_a_malformed_body_is_422(client, session_factory, route):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    res = client.post(f"/omnichannel/contacts/{cid}/{route}", content=b"{not json",
                      headers={**_auth(client), "content-type": "application/json"})
    assert res.status_code == 422
    assert res.json()["detail"] == "Request body must be valid JSON."


# ── the statement log ───────────────────────────────────────────────────────
@pytest.fixture
def sql_log():
    """Every statement, commit and rollback issued through any engine, in order
    (statements cut at 80 characters)."""
    from sqlalchemy.engine import Engine

    records: List[str] = []

    def on_execute(conn, cursor, statement, parameters, context, executemany):
        records.append(" ".join(statement.split())[:80])

    def on_commit(conn):
        records.append("COMMIT")

    def on_rollback(conn):
        records.append("ROLLBACK")

    event.listen(Engine, "before_cursor_execute", on_execute)
    event.listen(Engine, "commit", on_commit)
    event.listen(Engine, "rollback", on_rollback)
    try:
        yield records
    finally:
        event.remove(Engine, "before_cursor_execute", on_execute)
        event.remove(Engine, "commit", on_commit)
        event.remove(Engine, "rollback", on_rollback)


def test_sql_log_control_records_statements_and_commits(session_factory, sql_log):
    probe = session_factory()
    probe.execute(text("select 1"))
    probe.commit()
    probe.close()
    assert any(s.startswith("select 1") for s in sql_log)
    assert "COMMIT" in sql_log


# ── A2: sign-in is checked by token signature alone, before the body ────────
def _resigned(scn: Scenario, kind: str) -> Dict[str, str]:
    """The scenario's own valid bearer, re-signed the wrong way (or not at all)."""
    from jose import jwt
    from datetime import datetime, timedelta, timezone

    from app.config import settings

    if kind == "missing":
        return {}
    if kind == "malformed":
        return {"Authorization": "Bearer not-a-real-token"}
    claims = jwt.get_unverified_claims(scn.headers["Authorization"].split(" ", 1)[1])
    if kind == "wrong_secret":
        secret = "a-different-signing-secret-0123456789"
    else:
        secret = settings.jwt_secret
        claims["exp"] = int((datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp())
    return {"Authorization": "Bearer " + jwt.encode(claims, secret, algorithm=settings.jwt_algorithm)}


@pytest.mark.parametrize("scenario", SIGNED_IN_SCENARIOS, indirect=True)
@pytest.mark.parametrize("kind", ["missing", "malformed", "wrong_secret", "expired"])
def test_a_token_that_fails_its_signature_check_is_refused_without_a_statement(scenario, kind, sql_log):
    headers = _resigned(scenario, kind)
    sql_log.clear()
    run = asyncio.run(_drive(scenario, hold=False, headers=headers))
    assert run.status == 401, run.body
    assert run.receive_calls == 0, "the body was requested for a request that is not signed in"
    assert sql_log == [], f"{len(sql_log)} statement(s) ran, first: {sql_log[0]!r}"


# ── A3: a correctly signed token the server no longer accepts ───────────────
@pytest.mark.parametrize("scenario", SIGNED_IN_SCENARIOS, indirect=True)
def test_a_suspended_tenant_is_refused_with_403(scenario, session_factory):
    from app.models import DEFAULT_TENANT_ID
    from app.services.tenant_service import TenantService

    db = session_factory()
    try:
        TenantService(db).suspend(DEFAULT_TENANT_ID)
    finally:
        db.close()
    run = asyncio.run(_drive(scenario, hold=False))
    assert run.status == 403, run.body


@pytest.mark.parametrize("scenario", [n for n in SIGNED_IN_SCENARIOS if "inbox" not in n], indirect=True)
def test_a_signed_token_for_an_unknown_user_is_401(scenario):
    from jose import jwt

    from app.config import settings

    claims = jwt.get_unverified_claims(scenario.headers["Authorization"].split(" ", 1)[1])
    claims["sub"] = "no-such-user"
    token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    run = asyncio.run(_drive(scenario, hold=False, headers={"Authorization": f"Bearer {token}"}))
    assert run.status == 401, run.body
    assert run.json()["detail"] == "Could not validate credentials"


# ── A4: token route product and allow-list answers ──────────────────────────
def test_an_unknown_product_is_404_on_the_token_route(connector_client):
    res = connector_client.post("/mcp/no-such-product/oauth/token", data={"grant_type": "password"})
    assert res.status_code == 404


def test_a_client_outside_the_allow_list_is_403_on_the_token_route(connector_client):
    from modules.connector import registry
    from tests.connector_support import make_env

    registry.set_env_for_tests(make_env({"CONNECTOR_ALLOWED_CLIENT_CIDRS": "10.9.8.0/24"}))
    res = connector_client.post("/mcp/acme/oauth/token", data={"grant_type": "password"})
    assert res.status_code == 403
    assert "forbidden" in res.text.lower()


# ── A5: the token body is read up to a fixed size ───────────────────────────
TOKEN_BODY_CAP = 64 * 1024


def _token_body(total: int) -> bytes:
    """A form body of exactly `total` bytes: an unknown code plus padding."""
    head = urlencode({"grant_type": "authorization_code", "code": "c", "code_verifier": "v" * 50,
                      "client_id": "x", "redirect_uri": REDIRECT}) + "&pad="
    return (head + "p" * (total - len(head))).encode()


def _sized_token_scenario(body: bytes) -> Scenario:
    return Scenario("token_sized", "/mcp/acme/oauth/token", {}, body,
                    "application/x-www-form-urlencoded", 400, [], [], lambda run: None, scheme="https")


def test_a_token_body_declared_over_the_cap_is_413_without_reading_it(connector_client, sql_log):
    scn = _sized_token_scenario(_token_body(TOKEN_BODY_CAP + 1))
    sql_log.clear()
    run = asyncio.run(_drive(scn, hold=False))
    assert run.status == 413, run.body
    assert run.receive_calls == 0, "a body declared over the cap was still read"
    assert sql_log == [], f"{len(sql_log)} statement(s) ran, first: {sql_log[0]!r}"


def test_a_chunked_token_body_that_crosses_the_cap_is_413(connector_client):
    scn = _sized_token_scenario(_token_body(TOKEN_BODY_CAP * 2))
    run = asyncio.run(_drive(scn, hold=False, length="omit", chunk=8 * 1024))
    assert run.status == 413, run.body


def test_a_token_body_of_exactly_the_cap_is_processed_normally(connector_client):
    body = _token_body(TOKEN_BODY_CAP)
    assert len(body) == TOKEN_BODY_CAP
    run = asyncio.run(_drive(_sized_token_scenario(body), hold=False))
    assert run.status == 400, run.body
    assert run.json() == {"error": "invalid_grant"}


def test_a_chunked_token_body_of_exactly_the_cap_is_processed_normally(connector_client):
    run = asyncio.run(_drive(_sized_token_scenario(_token_body(TOKEN_BODY_CAP)), hold=False,
                             length="omit", chunk=8 * 1024))
    assert run.status == 400, run.body
    assert run.json() == {"error": "invalid_grant"}


# ── a client that leaves during the body ────────────────────────────────────
@pytest.mark.parametrize("scenario", SCENARIOS, indirect=True)
def test_a_client_that_leaves_during_the_body_causes_no_server_error(scenario, sql_log):
    sql_log.clear()
    try:
        run = asyncio.run(_drive(scenario, hold=False, disconnect=True))
    except Exception as exc:  # noqa: BLE001 - the app itself must not raise
        pytest.fail(f"the app raised when the client left: {type(exc).__name__}: {exc}")
    assert run.status is None or run.status < 500, f"a {run.status} was sent: {run.body!r}"
    if not scenario.name.startswith("token"):
        assert sql_log == [], f"{len(sql_log)} statement(s) ran, first: {sql_log[0]!r}"


# ── whatever the content type, nothing runs before the body is requested ────
_CONTENT_TYPES = [
    "multipart/mixed; boundary=x",
    "multipart/related; boundary=x",
    "multipart/alternative; boundary=x",
    "text/plain",
    "application/octet-stream",
    None,
    "MULTIPART/FORM-DATA; boundary=x",
]


@pytest.mark.parametrize("scenario", ["submit_json", "resubmit_json", "template_json", "interactive_json"],
                         indirect=True)
@pytest.mark.parametrize("content_type", _CONTENT_TYPES, ids=lambda c: str(c).split(";")[0].replace("/", "-"))
def test_no_statement_runs_before_the_body_arrives_whatever_the_content_type(
        scenario, content_type, sql_log, tracker):
    sql_log.clear()
    seen: Dict[str, Any] = {}

    def sample() -> int:
        seen["statements"] = [statement for statement in sql_log]
        seen["open"] = len(tracker())
        return seen["open"]

    run = asyncio.run(_drive(scenario, hold=True, sample=sample, ctype=content_type, strict=False))
    if run.receive_calls:  # when the route never asks for a body, there is no wait to inspect
        assert not seen["statements"], (
            f"{len(seen['statements'])} statement(s) ran before the body was requested, "
            f"first: {seen['statements'][0]!r}"
        )
        assert seen["open"] == 0, f"{seen['open']} session(s) held a transaction while the body was pending"
    assert run.status is None or run.status < 500, f"a {run.status} was sent: {run.body!r}"


# ═════════════════════════════════════════════════════════════════════════════
# A refused request leaves nothing behind, sign-in covers the token kind,
# malformed multipart answers 400
# ═════════════════════════════════════════════════════════════════════════════


# ── memory: a refused request does not stay reachable ───────────────────────
def _requests_holding(marker: bytes, forms: bool = False) -> int:
    """Live `Request` objects whose cached body contains `marker`; with `forms`, also
    those that hold a parsed form (and so its uploaded files)."""
    from starlette.requests import Request

    gc.collect()
    held = 0
    for obj in gc.get_objects():
        try:
            if not isinstance(obj, Request):
                continue
            body = getattr(obj, "_body", None)
            if (body is not None and marker in body) or (forms and getattr(obj, "_form", None) is not None):
                held += 1
        except ReferenceError:
            continue
    return held


def _open_spooled_files() -> int:
    gc.collect()
    count = 0
    for obj in gc.get_objects():
        try:
            if isinstance(obj, tempfile.SpooledTemporaryFile) and not obj.closed:
                count += 1
        except ReferenceError:
            continue
    return count


def test_memory_scan_control_sees_a_live_request_and_an_open_file():
    from starlette.requests import Request

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    base_requests = _requests_holding(b"control-marker")  # earlier tests in this process may hold some
    base_files = _open_spooled_files()
    request = Request({"type": "http", "method": "POST", "headers": [], "query_string": b""}, receive)
    request._body = b"head-control-marker-tail"
    assert _requests_holding(b"control-marker") == base_requests + 1
    request._form = object()
    assert _requests_holding(b"no-such-marker", forms=True) >= 1
    spooled = tempfile.SpooledTemporaryFile(max_size=10)
    assert _open_spooled_files() == base_files + 1
    spooled.close()
    assert _open_spooled_files() == base_files
    del request
    assert _requests_holding(b"control-marker") == base_requests


REFUSAL_REQUESTS = 5


def _refused_headers(scn: Scenario, kind: str, session_factory) -> Optional[Dict[str, str]]:
    """Set up one way a correctly signed request is refused after the body; returns
    the headers to send (None = the scenario's own)."""
    from jose import jwt

    from app.config import settings
    from app.models import DEFAULT_TENANT_ID

    if kind == "unknown_user":
        claims = jwt.get_unverified_claims(scn.headers["Authorization"].split(" ", 1)[1])
        claims["sub"] = "no-such-user"
        token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        return {"Authorization": f"Bearer {token}"}
    if kind == "embed_without_workspace":
        claims = jwt.get_unverified_claims(scn.headers["Authorization"].split(" ", 1)[1])
        claims.pop("workspaceId")
        token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        return {"Authorization": f"Bearer {token}"}
    db = session_factory()
    try:
        if kind == "suspended_tenant":
            from app.services.tenant_service import TenantService

            TenantService(db).suspend(DEFAULT_TENANT_ID)
        elif kind == "module_off":
            from app.services.app_store_service import AppStoreService

            AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
    finally:
        db.close()
    return None


_REFUSALS = [
    ("submit_json", "unknown_user"), ("submit_json", "suspended_tenant"),
    ("resubmit_json", "unknown_user"), ("resubmit_json", "suspended_tenant"),
    ("template_json", "unknown_user"), ("template_json", "suspended_tenant"),
    ("interactive_json", "unknown_user"), ("interactive_json", "suspended_tenant"),
    ("template_inbox_json", "suspended_tenant"), ("template_inbox_json", "embed_without_workspace"),
    ("template_inbox_json", "module_off"),
    ("interactive_inbox_json", "suspended_tenant"), ("interactive_inbox_json", "embed_without_workspace"),
    ("interactive_inbox_json", "module_off"),
]


@pytest.mark.parametrize("scenario,kind", _REFUSALS, indirect=["scenario"])
def test_a_refused_request_does_not_stay_in_memory(scenario, kind, session_factory):
    import dataclasses

    headers = _refused_headers(scenario, kind, session_factory)
    markers = [f"retained-{uuid.uuid4().hex}-{i}".encode() for i in range(REFUSAL_REQUESTS)]
    statuses = set()
    for marker in markers:
        body = json.dumps({"filler": marker.decode() + "x" * (512 * 1024)}).encode()
        scn = dataclasses.replace(scenario, body=body, content_type="application/json")
        statuses.add(asyncio.run(_drive(scn, hold=False, headers=headers)).status)
    assert statuses and all(s in (401, 403) for s in statuses), statuses  # every request was refused
    held = sum(_requests_holding(marker) for marker in markers)
    assert held == 0, f"{held} refused request(s) still hold their body in memory"


@pytest.mark.parametrize("scenario,kind", _REFUSALS, indirect=["scenario"])
def test_a_refused_upload_does_not_leave_its_file_open(scenario, kind, session_factory):
    import dataclasses

    headers = _refused_headers(scenario, kind, session_factory)
    field_name = "file:resume" if scenario.name.startswith(("submit", "resubmit")) else "file"
    opened_before = _open_spooled_files()
    forms_before = _requests_holding(b"no-such-marker", forms=True)
    statuses = set()
    for _ in range(REFUSAL_REQUESTS):
        body, ctype = _multipart(
            data={"payload": json.dumps({"answers": {}})},
            files=[(field_name, ("big.bin", os.urandom(2 * 1024 * 1024), "application/octet-stream"))],
        )
        scn = dataclasses.replace(scenario, body=body, content_type=ctype)
        statuses.add(asyncio.run(_drive(scn, hold=False, headers=headers)).status)
    assert statuses and all(s in (401, 403) for s in statuses), statuses
    forms_after = _requests_holding(b"no-such-marker", forms=True)
    assert forms_after - forms_before == 0, "a refused upload's parsed form is still reachable"
    assert _open_spooled_files() - opened_before == 0, "refused uploads left temp files open"


# ── a token of the wrong kind is refused before the body ────────────────────
def _wrong_kind_token(kind: str) -> str:
    from app.models import DEFAULT_TENANT_ID
    from app.security import create_access_token

    if kind == "profile":
        return create_access_token({"sub": "someone", "tenant_id": DEFAULT_TENANT_ID, "kind": "profile"})
    if kind == "visitor":
        from modules.omnichannel.models import Channel
        from modules.omnichannel.webchat_auth import mint_visitor_token

        channel = Channel(id="ch-visitor", tenant_id=DEFAULT_TENANT_ID, widget_token_epoch=0)
        return mint_visitor_token(channel)[0]
    return create_access_token({"tenant_id": DEFAULT_TENANT_ID})  # no_subject


@pytest.fixture
def forms_embed_token(client, session_factory):
    ws = _default_workspace_id(session_factory)
    return _inbox_headers(client, session_factory, ws)["Authorization"].split(" ", 1)[1]


_FORM_ROUTES = ["submit_json", "submit_multipart", "resubmit_json", "resubmit_multipart"]
_CONVERSATION_ROUTES = ["template_json", "template_multipart", "interactive_json", "interactive_multipart"]


@pytest.mark.parametrize("scenario", _FORM_ROUTES + _CONVERSATION_ROUTES, indirect=True)
@pytest.mark.parametrize("kind", ["profile", "visitor", "no_subject"])
def test_a_token_that_is_not_a_sign_in_token_is_refused_before_the_body(scenario, kind, sql_log):
    token = _wrong_kind_token(kind)
    sql_log.clear()
    run = asyncio.run(_drive(scenario, hold=False, headers={"Authorization": f"Bearer {token}"}))
    assert run.status == 401, run.body
    assert run.receive_calls == 0, "the body was requested for a token that is not a sign-in token"
    assert sql_log == [], f"{len(sql_log)} statement(s) ran, first: {sql_log[0]!r}"


@pytest.mark.parametrize("scenario", _FORM_ROUTES, indirect=True)
def test_an_embed_token_is_refused_before_the_body_on_form_routes(scenario, forms_embed_token, sql_log):
    sql_log.clear()
    run = asyncio.run(_drive(scenario, hold=False, headers={"Authorization": f"Bearer {forms_embed_token}"}))
    assert run.status == 401, run.body
    assert run.receive_calls == 0, "the body was requested for an embed token on a staff route"
    assert sql_log == [], f"{len(sql_log)} statement(s) ran, first: {sql_log[0]!r}"


# ── malformed multipart is a 400 ────────────────────────────────────────────
def _malformed_multipart(kind: str) -> Tuple[bytes, str]:
    if kind == "wrong_boundary":
        return b'--other\r\nContent-Disposition: form-data; name="payload"\r\n\r\n{}\r\n--other--\r\n', \
            "multipart/form-data; boundary=right"
    if kind == "missing_boundary":
        return b'--b\r\nContent-Disposition: form-data; name="payload"\r\n\r\n{}\r\n--b--\r\n', \
            "multipart/form-data"
    if kind == "missing_part_name":
        return b"--b\r\nContent-Disposition: form-data\r\n\r\nvalue\r\n--b--\r\n", \
            "multipart/form-data; boundary=b"
    big = b"x" * (1024 * 1024 + 16)
    return b'--b\r\nContent-Disposition: form-data; name="payload"\r\n\r\n' + big + b"\r\n--b--\r\n", \
        "multipart/form-data; boundary=b"


@pytest.mark.parametrize("scenario", ["submit_json", "resubmit_json", "template_json", "interactive_json"],
                         indirect=True)
@pytest.mark.parametrize("kind", ["wrong_boundary", "missing_boundary", "missing_part_name", "oversize_text_part"])
def test_a_malformed_multipart_body_is_answered_400(scenario, kind, sql_log):
    import dataclasses

    body, ctype = _malformed_multipart(kind)
    scn = dataclasses.replace(scenario, body=body, content_type=ctype)
    sql_log.clear()
    try:
        run = asyncio.run(_drive(scn, hold=False))
    except Exception as exc:  # noqa: BLE001 - the app itself must not raise
        pytest.fail(f"the app raised on a malformed multipart body: {type(exc).__name__}: {exc}")
    assert run.status == 400, f"{run.status}: {run.body!r}"
    assert sql_log == [], f"{len(sql_log)} statement(s) ran, first: {sql_log[0]!r}"


# ── token route: an over-cap refusal carries the no-store headers ───────────
@pytest.mark.parametrize("shape", ["declared", "chunked"])
def test_an_over_cap_token_body_is_refused_with_no_store_headers(connector_client, shape):
    over = _token_body(TOKEN_BODY_CAP * 2)
    scn = _sized_token_scenario(over)
    if shape == "declared":
        run = asyncio.run(_drive(scn, hold=False))
    else:
        run = asyncio.run(_drive(scn, hold=False, length="omit", chunk=8 * 1024))
    assert run.status == 413, run.body
    assert run.headers.get("cache-control") == "no-store", run.headers
    assert run.headers.get("pragma") == "no-cache", run.headers


# ── token route: unusual bodies ─────────────────────────────────────────────
def test_a_token_client_that_leaves_part_way_is_treated_as_an_empty_form(connector_client):
    body = _token_body(400)
    run = asyncio.run(_drive(_sized_token_scenario(body), hold=False, length="omit", chunk=100, leave_after=1))
    assert run.status == 400, run.body
    # the first 100 bytes name a grant type; an empty form has none
    assert run.json() == {"error": "unsupported_grant_type"}


def _drive_token(scn: Scenario, **kwargs) -> Run:
    try:
        return asyncio.run(_drive(scn, hold=False, **kwargs))
    except Exception as exc:  # noqa: BLE001 - the app itself must not raise
        pytest.fail(f"the app raised: {type(exc).__name__}: {exc}")


def test_a_token_body_with_a_non_integer_length_is_read_normally(connector_client):
    run = _drive_token(_sized_token_scenario(_token_body(400)), length="abc")
    assert run.status == 400, run.body
    assert run.json() == {"error": "invalid_grant"}


def test_a_token_body_with_a_non_integer_length_still_counts_against_the_cap(connector_client):
    run = _drive_token(_sized_token_scenario(_token_body(TOKEN_BODY_CAP * 2)), length="abc", chunk=8 * 1024)
    assert run.status == 413, run.body
