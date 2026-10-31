"""Plan 39 (sprint-5) - RED tests: Redis password + separate frontend network.

Parses the REAL repo files (no Docker needed): `docker-compose.yml` via
yaml.safe_load, `scripts/blue_green_deploy.sh`, `.github/workflows/deploy.yml`
and `DEPLOY.md` as text. AC-39-08/09/10 are live-proof or review items and are
deliberately NOT covered here.

No password value appears in this file or may appear in the repo files it
reads (AC-39-01 guard below).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
SCRIPT_PATH = REPO_ROOT / "scripts" / "blue_green_deploy.sh"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
DEPLOY_MD_PATH = REPO_ROOT / "DEPLOY.md"
CONFIG_PATH = REPO_ROOT / "service_backend" / "app" / "config.py"

NET = "foundryx_ss_network"
EDGE = "foundryx_ss_edge"


@pytest.fixture(scope="module")
def compose():
    with open(COMPOSE_PATH) as f:
        return yaml.safe_load(f)


def _net_names(service: dict) -> set:
    nets = service.get("networks") or []
    return set(nets.keys()) if isinstance(nets, dict) else set(nets)


def _script_lines():
    """(1-based line number, stripped text) of every non-comment script line."""
    out = []
    for i, raw in enumerate(SCRIPT_PATH.read_text().splitlines(), start=1):
        s = raw.strip()
        if s and not s.startswith("#"):
            out.append((i, s))
    return out


# ── AC-39-01 ─────────────────────────────────────────────────────────────────
def test_ac_39_01_redis_requirepass_uses_strict_interpolation(compose):
    command = compose["services"]["redis"]["command"]
    text = " ".join(command) if isinstance(command, list) else str(command)
    assert "--requirepass" in text, f"AC-39-01: redis needs --requirepass, got: {text}"
    assert re.search(r"--requirepass\s+\"?\$\{REDIS_PASSWORD:\?", text), (
        "AC-39-01: the value must be ${REDIS_PASSWORD:?...} so a missing secret stops compose"
    )
    assert "--appendonly yes" in text, "control: existing redis flags must survive"


def test_ac_39_01_no_literal_password_in_repo_files():
    """The only legal forms are the interpolation, a `<placeholder>` or a
    workflow `${{ secrets... }}` reference."""
    offenders = []
    for path in (COMPOSE_PATH, SCRIPT_PATH, WORKFLOW_PATH, DEPLOY_MD_PATH):
        for n, line in enumerate(path.read_text().splitlines(), start=1):
            for m in re.finditer(r"REDIS_PASSWORD=(\S*)", line):
                val = m.group(1).strip("`\"'")
                if val and not val.startswith(("$", "<")):
                    offenders.append(f"{path.name}:{n}: {line.strip()}")
            for m in re.finditer(r"redis://default:([^@\s]*)@", line):
                if not m.group(1).startswith(("$", "<")):
                    offenders.append(f"{path.name}:{n}: {line.strip()}")
            for m in re.finditer(r"--requirepass\s+(\S+)", line):
                if not m.group(1).strip("\"'").startswith("$"):
                    offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert not offenders, f"literal Redis password in repo files: {offenders}"


# ── AC-39-02 ─────────────────────────────────────────────────────────────────
def test_ac_39_02_redis_url_uses_two_argument_default_user_form(compose):
    # WHY `default:` and not the bare `redis://:pw@`: while Redis is still open
    # (deploy steps 1-5) it refuses the ONE-argument `AUTH <pw>` but accepts the
    # TWO-argument `AUTH default <pw>`. A `redis://:` URL would break every
    # client during the rollout window, so it must fail this test.
    url = compose["x-backend-env"]["REDIS_URL"]
    assert not url.startswith("redis://:"), "one-argument AUTH form breaks the rollout"
    assert url.startswith("redis://default:${REDIS_PASSWORD"), url
    assert url.endswith("@redis:6379/0"), url


def test_ac_39_02_every_redis_client_service_gets_the_same_url(compose):
    expected = compose["x-backend-env"]["REDIS_URL"]
    carriers = {
        name
        for name, svc in compose["services"].items()
        if "REDIS_URL" in (svc.get("environment") or {})
    }
    assert {"backend_blue", "backend_green", "worker_workflow", "worker_jobs", "worker_omni", "beat"} <= carriers
    for name in carriers:
        assert compose["services"][name]["environment"]["REDIS_URL"] == expected, name


# ── AC-39-03 ─────────────────────────────────────────────────────────────────
def test_ac_39_03_deploy_workflow_renders_redis_password_secret():
    assert "REDIS_PASSWORD=${{ secrets.REDIS_PASSWORD }}" in WORKFLOW_PATH.read_text()


# ── AC-39-04 / 05 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", ["frontend_blue", "frontend_green"])
def test_ac_39_04_frontends_are_on_the_edge_network_only(compose, name):
    assert _net_names(compose["services"][name]) == {EDGE}


@pytest.mark.parametrize("name", ["backend_blue", "backend_green"])
def test_ac_39_05_backends_on_both_networks_with_backend_alias_on_edge(compose, name):
    nets = compose["services"][name]["networks"]
    assert isinstance(nets, dict), "aliases require the mapping form"
    assert set(nets) == {NET, EDGE}
    assert "backend" in (nets[EDGE] or {}).get("aliases", [])


@pytest.mark.parametrize("name", ["db", "redis", "pgbackups", "worker_workflow", "worker_jobs", "worker_omni", "beat"])
def test_ac_39_05_infra_and_workers_stay_off_the_edge_network(compose, name):
    assert _net_names(compose["services"][name]) == {NET}


def test_ac_39_05_network_definitions(compose):
    nets = compose["networks"]
    assert EDGE in nets, "edge network must be declared"
    assert not nets[EDGE].get("internal"), "edge must not be internal: published ports need it"
    pinned = nets[NET]["ipam"]["config"][0]
    assert pinned == {"subnet": "172.21.0.0/16", "gateway": "172.21.0.1"}


# ── AC-39-06 / 07 (script ordering, by line position) ────────────────────────
def _old_color_rm_line(lines):
    hits = [n for n, s in lines if "compose rm -f" in s and "${OLD}" in s]
    assert len(hits) == 1, f"control: expected exactly one old-color `rm -f` line, got {hits}"
    return hits[0]


def test_ac_39_06_infra_step_never_recreates_redis_before_clients_move():
    lines = _script_lines()
    rm_old = _old_color_rm_line(lines)
    infra = [
        (n, s)
        for n, s in lines
        if n < rm_old and "compose up -d" in s and re.search(r"\bredis\b", s)
    ]
    assert infra, "control: an infra `up -d ... redis` line must exist before the old color is removed"
    for n, s in infra:
        assert "--no-recreate" in s, f"line {n}: {s} would recreate redis too early"
    # the network-recreate fallback must still exist
    text = SCRIPT_PATH.read_text()
    assert "NETWORK_RECREATE_SIGNATURE" in text and "down --remove-orphans" in text


def test_ac_39_07_redis_recreated_after_old_color_removed():
    lines = _script_lines()
    rm_old = _old_color_rm_line(lines)
    ups = [
        n
        for n, s in lines
        if re.search(r"compose up -d\b.*\bredis\b", s) and "--no-recreate" not in s and n > rm_old
    ]
    assert len(ups) == 1, f"expected one plain `docker compose up -d redis` after line {rm_old}, got {ups}"


def test_ac_39_07_auth_check_after_redis_up_with_env_password_and_hard_failure():
    lines = _script_lines()
    rm_old = _old_color_rm_line(lines)
    redis_up = next(
        (n for n, s in lines if re.search(r"compose up -d\b.*\bredis\b", s) and "--no-recreate" not in s and n > rm_old),
        None,
    )
    assert redis_up is not None, "AC-39-07: no `docker compose up -d redis` after the old color removal"
    after = [(n, s) for n, s in lines if n > redis_up]
    cli = [(n, s) for n, s in after if "redis-cli" in s]
    assert cli, "AC-39-07: no redis-cli check after the redis recreate"
    assert any("REDISCLI_AUTH" in s for _, s in after), "password must travel via REDISCLI_AUTH"
    for n, s in cli:
        assert not re.search(r"(^|\s)(-a|--pass|--askpass)(\s|=|$)", s), f"line {n}: password on a command line"
    joined = "\n".join(s for _, s in after)
    assert "PONG" in joined and "NOAUTH" in joined, "must require PONG (authed) and refusal (unauthed)"
    assert re.search(r"\bexit 1\b", joined), "a failed check must exit non-zero"
    # the check must sit before the final summary/active-color persistence is irrelevant;
    # but it must come after the redis recreate, asserted by construction (`after`).


# ── AC-39-11 ─────────────────────────────────────────────────────────────────
def test_ac_39_11_deploy_md_documents_secret_network_and_url_form():
    text = DEPLOY_MD_PATH.read_text()
    assert "REDIS_PASSWORD" in text
    assert EDGE in text
    assert "redis://default:" in text


def test_ac_39_11_local_dev_default_redis_url_stays_passwordless():
    text = CONFIG_PATH.read_text()
    m = re.search(r'redis_url:\s*str\s*=\s*"([^"]+)"', text)
    assert m, "control: redis_url default must be found"
    assert m.group(1) == "redis://localhost:6379/0"
