"""Routes that wait for a request body keep their database work off the event loop
and hold no transaction while they wait.

Rule (storage-and-background-jobs.md): never hold an app-DB read transaction across
a wait, and never run synchronous session work on the event loop thread. Five
`async def` routes read the database during sign-in and pre-checks, then wait for
the request body, then do more database work:

  1. connector   POST /mcp/{p}/oauth/token                   (form body)
  2. forms       POST /forms/{id}/submissions                (JSON and multipart)
  3. forms       POST /submissions/{id}/resubmit             (JSON and multipart)
  4. omnichannel POST /omnichannel/contacts/{id}/template    (JSON and multipart)
  5. omnichannel POST /omnichannel/contacts/{id}/interactive (JSON and multipart)

The ASGI app is driven directly with a `receive` callable that blocks until the test
releases the body, so the wait is real whatever a client transport buffers (same
approach as test_omnichannel_gateway_key_read_release.py). Thread identity is
recorded by spies on the session-touching calls and compared with the thread that
runs the event loop. The in-memory suite cannot see pool behaviour, so nothing here
counts connections: it asserts on session state and on threads.

Existing suites that already pin the answers of these routes (B4):
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
import json
import threading
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
    """Records (label, thread id) for every call of the wrapped session-touching
    functions, then calls through to the real one."""

    def __init__(self, monkeypatch):
        self._mp = monkeypatch
        self.calls: List[Tuple[str, int]] = []

    def watch(self, label: str, targets: List[Tuple[Any, str]]) -> None:
        original = getattr(targets[0][0], targets[0][1])
        calls = self.calls

        def wrapper(*args, **kwargs):
            calls.append((label, threading.get_ident()))
            return original(*args, **kwargs)

        for owner, attr in targets:
            self._mp.setattr(owner, attr, wrapper)

    def labels(self) -> List[str]:
        return [label for label, _ in self.calls]

    def threads(self, label: str) -> List[int]:
        return [thread for name, thread in self.calls if name == label]


@pytest.fixture
def spies(monkeypatch):
    return Spies(monkeypatch)


# ── the driver ───────────────────────────────────────────────────────────────
@dataclass
class Run:
    loop_thread: int = 0
    receive_thread: Optional[int] = None
    receive_calls: int = 0
    sampled: Optional[int] = None
    status: Optional[int] = None
    headers: Dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def json(self) -> Any:
        return json.loads(self.body)


async def _drive(scn: "Scenario", *, hold: bool, sample: Optional[Callable[[], int]] = None,
                 headers: Optional[Dict[str, str]] = None, path: Optional[str] = None) -> Run:
    """POST the scenario straight into the ASGI app. With `hold` the body is withheld
    until the app asks for it (so every dependency and pre-check has finished) and
    `sample()` is taken at that moment; without it the body is available at once and
    the run simply records whether the app ever asked for it."""
    run = Run(loop_thread=threading.get_ident())
    release = asyncio.Event()
    if not hold:
        release.set()
    first_receive = asyncio.Event()
    sent: List[int] = []

    async def receive():
        run.receive_calls += 1
        run.receive_thread = threading.get_ident()
        first_receive.set()
        await release.wait()
        if sent:
            if hold:
                await asyncio.Event().wait()  # no disconnect during the test
            return {"type": "http.disconnect"}
        sent.append(1)
        return {"type": "http.request", "body": scn.body, "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            run.status = message["status"]
            run.headers = {k.decode().lower(): v.decode() for k, v in message["headers"]}
        elif message["type"] == "http.response.body":
            run.body += message.get("body", b"")

    use_path = path or scn.path
    raw_headers = [
        (b"host", b"testserver"),
        (b"content-type", scn.content_type.encode()),
        (b"content-length", str(len(scn.body)).encode()),
    ]
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


def _omni_setup(request, *, phone_number_id: str):
    client = request.getfixturevalue("client")
    sf = request.getfixturevalue("session_factory")
    ws = _default_workspace_id(sf)
    ch = _seed_channel(sf, ws, phone_number_id=phone_number_id)
    cid = _seed_contact(sf, ws, phone="+60190000001")
    return client, sf, ws, ch, cid


def _template_scenario(request, *, multipart: bool) -> Scenario:
    client, sf, ws, ch, cid = _omni_setup(request, phone_number_id="pn-body-tpl")
    headers = _auth(client)
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

    def check(run: Run) -> None:
        out = run.json()
        assert out["messageType"] == "TEMPLATE"
        assert out["deliveryStatus"] == "SENT"
    return Scenario(name, f"/omnichannel/contacts/{cid}/template", dict(headers), body, ctype, 201,
                    _thread_watch("send_message"), ["enforce_thread_access", "send_message"], check,
                    ctx={"sf": sf, "ws": ws, "cid": cid, "client": client})


def _interactive_scenario(request, *, multipart: bool) -> Scenario:
    client, sf, ws, _ch, cid = _omni_setup(request, phone_number_id="pn-body-int")
    headers = _auth(client)
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

    def check(run: Run) -> None:
        out = run.json()
        assert out["messageType"] == "INTERACTIVE"
        assert out["deliveryStatus"] == "SENT"
    return Scenario(name, f"/omnichannel/contacts/{cid}/interactive", dict(headers), body, ctype, 201,
                    _thread_watch("send_interactive"), ["enforce_thread_access", "send_interactive"], check,
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
}
SCENARIOS = list(BUILDERS)
SIGNED_IN_SCENARIOS = [n for n in SCENARIOS if not n.startswith("token")]
CONVERSATION_SCENARIOS = [n for n in SCENARIOS if n.startswith(("template", "interactive"))]


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


# ── B1: no transaction is open while the route waits for its body ───────────
@pytest.mark.parametrize("scenario", SCENARIOS, indirect=True)
def test_no_transaction_is_open_while_the_route_waits_for_its_body(scenario, spies, tracker):
    _arm(scenario, spies)
    run = _run_held(scenario, tracker)
    assert run.sampled == 0, f"{run.sampled} session(s) held a transaction while the body was pending"
    assert run.status == scenario.status, run.body


# ── B2: session work runs on a worker thread, never on the event loop ───────
@pytest.mark.parametrize("scenario", SCENARIOS, indirect=True)
def test_session_work_runs_off_the_event_loop(scenario, spies, tracker):
    _arm(scenario, spies)
    run = _run_held(scenario, tracker)
    assert run.receive_thread == run.loop_thread, "the harness read the body off the loop thread"
    for label in scenario.expect:
        assert spies.threads(label), f"{label} was never called"
    for label, thread in spies.calls:
        assert thread != run.loop_thread, f"{label} ran on the event loop thread"
    assert run.status == scenario.status, run.body


# ═════════════════════════════════════════════════════════════════════════════
# Answers that must not change (B3 ordering, B4 responses, B5 real flow)
# ═════════════════════════════════════════════════════════════════════════════


# ── B3: sign-in and pre-checks still answer before the body is requested ────
@pytest.mark.parametrize("scenario", SIGNED_IN_SCENARIOS, indirect=True)
@pytest.mark.parametrize("sign_in", ["missing", "invalid"])
def test_a_request_without_valid_sign_in_is_refused_before_the_body_is_read(scenario, sign_in):
    headers = {} if sign_in == "missing" else {"Authorization": "Bearer not-a-real-token"}
    run = asyncio.run(_drive(scenario, hold=False, headers=headers))
    assert run.status == 401, run.body
    assert run.receive_calls == 0, "the body was requested before sign-in was checked"


@pytest.mark.parametrize("scenario", CONVERSATION_SCENARIOS, indirect=True)
def test_a_token_without_access_to_the_thread_is_refused_before_the_body_is_read(scenario):
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
    assert run.receive_calls == 0, "the body was requested before thread access was checked"


def test_a_throttled_client_is_refused_before_the_token_body_is_read(connector_client):
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
    assert run.receive_calls == 0, "the body was requested for a throttled client"


def _token_scenario_for(connector_client) -> Scenario:
    form = {"grant_type": "authorization_code", "code": "c", "code_verifier": "v" * 50,
            "client_id": "x", "redirect_uri": REDIRECT}
    return Scenario("token_throttled", "/mcp/acme/oauth/token", {}, urlencode(form).encode(),
                    "application/x-www-form-urlencoded", 429, [], [], lambda run: None, scheme="https")


def test_control_an_unthrottled_token_request_does_read_the_body(connector_client):
    scn = _token_scenario_for(connector_client)
    run = asyncio.run(_drive(scn, hold=False))
    assert run.status == 400, run.body  # unknown code: refused, but only after the body was read
    assert run.receive_calls >= 1


# ── B5: the real flow still works after the transaction ends ────────────────
@pytest.mark.parametrize("scenario", SCENARIOS, indirect=True)
def test_the_route_answers_correctly_once_the_body_arrives(scenario, spies, tracker):
    _arm(scenario, spies)
    run = _run_held(scenario, tracker)
    assert run.receive_calls >= 1
    assert run.status == scenario.status, run.body
    scenario.check(run)


# ── B4: token route (gaps in test_connector_oauth.py) ───────────────────────
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


# ── B4: form submit and resubmit (gaps in test_form_*.py) ───────────────────
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


# ── B4: conversation template and interactive sends ─────────────────────────
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
