"""claude-procedural red tests: the engine loop with a fake SDK client and a fake run_script."""
import io
import json
import re
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import trimesh
from PIL import Image

from planner3d_worker.claude.ledger import Ledger
from planner3d_worker.claude.routing import Routing
from planner3d_worker.claude.sandbox import RunResult
from planner3d_worker.engines.claude_procedural import ClaudeProceduralEngine, EngineFailure

CANARY = "sk-ant-api03-CANARY-KEY-0123456789"
SONNET, OPUS = "claude-sonnet-5-5", "claude-opus-5-5"
PRICES = {SONNET: {"input": 2.0, "output": 10.0, "cacheRead": 0.10}, OPUS: {"input": 4.0, "output": 20.0, "cacheRead": 0.20}}
DIMS = {"length": 1200, "width": 600, "height": 750}
USAGE = dict(input_tokens=1000, output_tokens=500, cache_read_input_tokens=2000, cache_creation_input_tokens=100)
USD_SONNET = (1100 * 2.0 + 500 * 10.0 + 2000 * 0.10) / 1e6
USD_OPUS = (1100 * 4.0 + 500 * 20.0 + 2000 * 0.20) / 1e6


def reply(script, usage=None):
    """A scripted SDK reply: text with a python block, plus usage."""
    text = f"Here is the script.\n```python\n{script}\n```\n"
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(**(usage or USAGE)),
    )


def box_script(tag, l=1200, w=600, h=750):
    return f"import trimesh\n# BOX {l} {w} {h} {tag}\n"


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.api_key = None
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        message = self.replies.pop(0)

        @contextmanager
        def ctx():
            yield SimpleNamespace(get_final_message=lambda: message)

        return ctx()


class FakeRunner:
    """Writes a real small GLB sized from the '# BOX l w h' marker; 'FAIL' in src = script error."""

    def __init__(self):
        self.sources = []
        self.work_files = []

    def __call__(self, src, work_dir, limits):
        self.sources.append(src)
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        if "FAIL" in src:
            return RunResult(ok=False, glb=None, stderr_tail="Traceback (most recent call last):\nNameError: FAIL-marker", seconds=0.1, reason="exit")
        l, w, h = (float(x) for x in re.search(r"# BOX (\S+) (\S+) (\S+)", src).groups())
        mesh = trimesh.creation.box(extents=(l / 1000, h / 1000, w / 1000))
        mesh.apply_translation((0, h / 2000, 0))
        glb = work_dir / "model.glb"
        glb.write_bytes(mesh.export(file_type="glb"))
        self.work_files.append([p for p in work_dir.iterdir()])
        return RunResult(ok=True, glb=glb, stderr_tail="", seconds=0.5, reason=None)


def _routing(tmp_path, cap=700, default_versions=2, categories=None):
    path = tmp_path / "routing.json"
    path.write_text(json.dumps({
        "spendCapUsd": cap,
        "prices": PRICES,
        "default": {"model": SONNET, "approach": "primitives", "maxVersions": default_versions, "effort": "medium"},
        "categories": categories if categories is not None else {
            "SRTWC": {"model": OPUS, "approach": "sdf", "maxVersions": 3, "effort": "high"},
        },
    }))
    return Routing.load(path)


def _photo(tmp_path, name="photo-1.png"):
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (200, 10, 10)).save(buf, "PNG")
    p = tmp_path / "in" / name
    p.parent.mkdir(exist_ok=True)
    p.write_bytes(buf.getvalue())
    return str(p)


def _make(tmp_path, replies, **kw):
    client = FakeClient(replies)
    runner = FakeRunner()
    ledger = Ledger(tmp_path / "ledger.jsonl")
    engine = ClaudeProceduralEngine(
        client=client, routing=kw.pop("routing", None) or _routing(tmp_path), ledger=ledger, run_script=runner
    )
    return engine, client, runner, ledger


def _run(engine, tmp_path, params=None, inputs=None):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    p = {"dimensionsMm": DIMS, **(params or {})}
    return engine.run("model", inputs or {"photo-1.png": _photo(tmp_path)}, p, out), out


def _last_user_text(call):
    content = call["messages"][-1]["content"]
    if isinstance(content, str):
        return content
    return "\n".join(b["text"] for b in content if b.get("type") == "text")


def _images(call):
    return [b for m in call["messages"] if isinstance(m["content"], list) for b in m["content"] if b.get("type") == "image"]


def test_kinds_is_model_only():
    assert ClaudeProceduralEngine(client=FakeClient([]), run_script=FakeRunner()).kinds == ["model"]


def test_two_versions_give_two_candidates_with_reports(tmp_path):
    engine, client, runner, _ = _make(tmp_path, [reply(box_script("v1", 1190)), reply(box_script("v2", 1200))])
    produced, out = _run(engine, tmp_path, {"productCode": "SRTWT5903"})
    assert sorted(produced) == [
        ("candidate-1.glb", "candidate"), ("candidate-1.json", "report"),
        ("candidate-2.glb", "candidate"), ("candidate-2.json", "report"),
    ]
    assert len(client.calls) == 2
    for name in ("candidate-1.glb", "candidate-2.glb"):
        assert (out / name).read_bytes()[:4] == b"glTF"
    r1 = json.loads((out / "candidate-1.json").read_text())
    r2 = json.loads((out / "candidate-2.json").read_text())
    # candidate-1 = the last version, candidate-2 = the one before
    assert "v2" in r1["script"] and "v1" in r2["script"]
    assert (r1["version"], r2["version"]) == (2, 1)
    for r in (r1, r2):
        assert r["engine"] == "claude-procedural" and r["model"] == SONNET
        assert set(r) >= {"engine", "model", "version", "usage", "usd", "seconds", "measuredMm", "specMm", "dimsErrorMm", "script"}
        assert r["specMm"] == DIMS
        assert r["usd"] == pytest.approx(USD_SONNET)
    assert r1["measuredMm"]["length"] == pytest.approx(1200, abs=0.5)
    assert r1["measuredMm"]["width"] == pytest.approx(600, abs=0.5)
    assert r1["measuredMm"]["height"] == pytest.approx(750, abs=0.5)
    assert r2["measuredMm"]["length"] == pytest.approx(1190, abs=0.5)
    assert abs(r2["dimsErrorMm"]["length"]) == pytest.approx(10, abs=0.5)


def test_refine_turn_carries_renders_and_measurements(tmp_path):
    engine, client, _, _ = _make(tmp_path, [reply(box_script("v1", 1190)), reply(box_script("v2"))])
    _run(engine, tmp_path)
    second = client.calls[1]
    assert len(_images(second)) >= 3 + 1  # three renders plus the original photo
    text = _last_user_text(second)
    assert "1190" in text and "1200" in text


def test_max_versions_three_gives_three_candidates(tmp_path):
    engine, client, _, _ = _make(
        tmp_path, [reply(box_script("v1")), reply(box_script("v2")), reply(box_script("v3"))], routing=_routing(tmp_path, default_versions=3)
    )
    produced, out = _run(engine, tmp_path)
    names = {n for n, _ in produced}
    assert names == {f"candidate-{i}.{e}" for i in (1, 2, 3) for e in ("glb", "json")}
    assert len(client.calls) == 3
    scripts = [json.loads((out / f"candidate-{i}.json").read_text())["script"] for i in (1, 2, 3)]
    assert "v3" in scripts[0] and "v2" in scripts[1] and "v1" in scripts[2]


def test_failed_first_version_feeds_the_error_and_needs_a_third_turn(tmp_path):
    engine, client, runner, _ = _make(
        tmp_path,
        [reply(box_script("FAIL")), reply(box_script("v2")), reply(box_script("v3"))],
        routing=_routing(tmp_path, default_versions=3),
    )
    produced, out = _run(engine, tmp_path)
    assert len(client.calls) == 3
    assert "NameError: FAIL-marker" in _last_user_text(client.calls[1])
    assert {n for n, _ in produced} >= {"candidate-1.glb", "candidate-2.glb"}
    scripts = [json.loads((out / f"candidate-{i}.json").read_text())["script"] for i in (1, 2)]
    assert "v3" in scripts[0] and "v2" in scripts[1]


def test_rejected_script_never_reaches_run_script_and_error_is_fed_back(tmp_path):
    engine, client, runner, _ = _make(
        tmp_path,
        [reply("import subprocess\n# BOX 1 1 1"), reply(box_script("v2")), reply(box_script("v3"))],
        routing=_routing(tmp_path, default_versions=3),
    )
    _run(engine, tmp_path)
    assert all("subprocess" not in s for s in runner.sources)
    assert "subprocess" in _last_user_text(client.calls[1])


def test_all_versions_failing_is_generation_failed(tmp_path):
    engine, client, _, _ = _make(tmp_path, [reply(box_script("FAIL")), reply(box_script("FAIL")), reply(box_script("FAIL"))])
    with pytest.raises(EngineFailure) as e:
        _run(engine, tmp_path)
    assert e.value.code == "generation_failed"
    assert str(e.value).startswith("generation_failed: ")


def test_only_one_good_version_is_generation_failed(tmp_path):
    engine, _, _, _ = _make(tmp_path, [reply(box_script("v1")), reply(box_script("FAIL")), reply(box_script("FAIL"))])
    with pytest.raises(EngineFailure) as e:
        _run(engine, tmp_path)
    assert e.value.code == "generation_failed"


def test_reply_without_a_script_counts_as_a_failed_version(tmp_path):
    no_code = SimpleNamespace(content=[SimpleNamespace(type="text", text="sorry")], usage=SimpleNamespace(**USAGE))
    engine, client, _, _ = _make(tmp_path, [no_code, no_code, no_code])
    with pytest.raises(EngineFailure) as e:
        _run(engine, tmp_path)
    assert e.value.code == "generation_failed"


def test_routing_by_category_code_picks_the_model(tmp_path):
    engine, client, _, ledger = _make(tmp_path, [reply(box_script("v1")), reply(box_script("v2")), reply(box_script("v3"))])
    _run(engine, tmp_path, {"category": {"code": "SRTWC", "name": "Water closets"}})
    assert [c["model"] for c in client.calls] == [OPUS] * 3
    assert ledger.total_usd() == pytest.approx(3 * USD_OPUS)


def test_unknown_category_uses_the_default_profile(tmp_path):
    engine, client, _, _ = _make(tmp_path, [reply(box_script("v1")), reply(box_script("v2"))])
    _run(engine, tmp_path, {"category": {"code": "NOPE", "name": "?"}})
    assert [c["model"] for c in client.calls] == [SONNET] * 2


def test_no_category_uses_the_default_profile(tmp_path):
    engine, client, _, _ = _make(tmp_path, [reply(box_script("v1")), reply(box_script("v2"))])
    _run(engine, tmp_path)
    assert {c["model"] for c in client.calls} == {SONNET}


def test_spend_cap_reached_stops_with_zero_calls(tmp_path):
    engine, client, runner, ledger = _make(tmp_path, [reply(box_script("v1")), reply(box_script("v2"))], routing=_routing(tmp_path, cap=10))
    ledger.append({"at": "2026-11-27T00:00:00Z", "jobRef": "old", "productCode": "X", "model": SONNET,
                   "inputTokens": 1, "outputTokens": 1, "cacheReadTokens": 0, "usd": 10.0})
    with pytest.raises(EngineFailure) as e:
        _run(engine, tmp_path)
    assert e.value.code == "spend_cap" and str(e.value).startswith("spend_cap: ")
    assert client.calls == [] and runner.sources == []


def test_spend_cap_is_rechecked_before_each_call(tmp_path):
    big = dict(input_tokens=2_000_000, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0)  # US$4 on sonnet
    engine, client, _, ledger = _make(
        tmp_path, [reply(box_script("v1"), big), reply(box_script("v2"))], routing=_routing(tmp_path, cap=3)
    )
    with pytest.raises(EngineFailure) as e:
        _run(engine, tmp_path)
    assert e.value.code == "spend_cap"
    assert len(client.calls) == 1
    assert ledger.total_usd() == pytest.approx(4.0)


def test_one_ledger_line_per_call_with_tokens_and_usd(tmp_path):
    engine, client, _, ledger = _make(tmp_path, [reply(box_script("v1")), reply(box_script("v2"))])
    _run(engine, tmp_path, {"productCode": "SRTWT5903"})
    lines = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert len(lines) == 2
    for line in lines:
        assert line["model"] == SONNET and line["productCode"] == "SRTWT5903"
        assert line["inputTokens"] == 1000 and line["outputTokens"] == 500 and line["cacheReadTokens"] == 2000
        assert line["usd"] == pytest.approx(USD_SONNET)
        assert line["at"] and "jobRef" in line


def test_api_key_never_reaches_outputs_or_the_script_runner(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", CANARY)
    engine, client, runner, _ = _make(tmp_path, [reply(box_script("v1")), reply(box_script("v2"))])
    client.api_key = CANARY
    produced, out = _run(engine, tmp_path, {"productCode": "SRTWT5903"})
    for path in out.rglob("*"):
        if path.is_file():
            assert CANARY.encode() not in path.read_bytes(), path.name
    assert all(CANARY not in s for s in runner.sources)
    for files in runner.work_files:
        for f in files:
            assert CANARY.encode() not in f.read_bytes()
    assert all(CANARY not in json.dumps(c, default=str) for c in client.calls)
    assert CANARY not in (tmp_path / "ledger.jsonl").read_text()


def test_drawing_is_sent_when_present(tmp_path):
    engine, client, _, _ = _make(tmp_path, [reply(box_script("v1")), reply(box_script("v2"))])
    _run(engine, tmp_path, inputs={"photo-1.png": _photo(tmp_path), "drawing.png": _photo(tmp_path, "drawing.png")})
    first = client.calls[0]
    content = first["messages"][0]["content"]
    assert sum(1 for b in content if b["type"] == "image") == 2


def test_photo_only_sends_one_image_on_the_first_turn(tmp_path):
    engine, client, _, _ = _make(tmp_path, [reply(box_script("v1")), reply(box_script("v2"))])
    _run(engine, tmp_path)
    assert sum(1 for b in client.calls[0]["messages"][0]["content"] if b["type"] == "image") == 1


def test_first_turn_text_carries_the_dimensions(tmp_path):
    engine, client, _, _ = _make(tmp_path, [reply(box_script("v1")), reply(box_script("v2"))])
    _run(engine, tmp_path)
    text = "\n".join(b["text"] for b in client.calls[0]["messages"][0]["content"] if b["type"] == "text")
    assert "1200" in text and "600" in text and "750" in text


def test_missing_client_without_a_key_is_no_api_key(tmp_path, monkeypatch):
    import planner3d_worker.keychain as keychain

    def _missing(*a, **k):
        raise keychain.KeychainError("no keychain item")

    monkeypatch.setattr(keychain, "read_secret", _missing)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    engine = ClaudeProceduralEngine(client=None, routing=_routing(tmp_path), ledger=Ledger(tmp_path / "l.jsonl"), run_script=FakeRunner())
    with pytest.raises(EngineFailure) as e:
        _run(engine, tmp_path)
    assert e.value.code == "no_api_key"


def test_build_engine_claude_knows_the_model_kind():
    from planner3d_worker.engines import build_engine

    assert "model" in build_engine("claude").kinds


def test_a_model_with_too_many_faces_fails_the_version_and_is_never_rendered(tmp_path, monkeypatch):
    import planner3d_worker.engines.claude_procedural as mod

    monkeypatch.setattr(mod, "MAX_FACES", 5)  # a box has 12
    rendered = []
    monkeypatch.setattr(mod, "render_views", lambda *a, **k: rendered.append(1) or {})
    engine, client, _, _ = _make(tmp_path, [reply(box_script("v1")), reply(box_script("v2"))])
    with pytest.raises(EngineFailure) as e:
        _run(engine, tmp_path)
    assert e.value.code == "generation_failed" and rendered == []
    assert "too many faces" in _last_user_text(client.calls[1])


def test_unknown_model_price_fails_before_any_call(tmp_path):
    routing = _routing(tmp_path)
    routing._prices = {}
    engine, client, _, _ = _make(tmp_path, [reply(box_script("v1")), reply(box_script("v2"))], routing=routing)
    with pytest.raises(EngineFailure) as e:
        _run(engine, tmp_path)
    assert e.value.code == "generation_failed" and "no price for model" in str(e.value)
    assert client.calls == []


def test_time_budget_skips_a_further_version_once_two_are_good(tmp_path):
    engine, client, _, _ = _make(
        tmp_path, [reply(box_script("v1")), reply(box_script("v2")), reply(box_script("v3"))], routing=_routing(tmp_path, default_versions=3)
    )
    engine.time_budget_s = 0.0
    produced, _ = _run(engine, tmp_path)
    assert len(client.calls) == 2
    assert {n for n, _r in produced} == {"candidate-1.glb", "candidate-1.json", "candidate-2.glb", "candidate-2.json"}


def test_time_budget_never_blocks_the_first_two_versions(tmp_path):
    engine, client, _, _ = _make(tmp_path, [reply(box_script("v1")), reply(box_script("v2"))])
    engine.time_budget_s = 0.0
    _run(engine, tmp_path)
    assert len(client.calls) == 2


def test_job_id_from_params_is_the_ledger_job_ref(tmp_path):
    engine, _, _, _ = _make(tmp_path, [reply(box_script("v1")), reply(box_script("v2"))])
    _run(engine, tmp_path, {"_jobId": "job-123"})
    lines = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert {l["jobRef"] for l in lines} == {"job-123"}


def test_over_budget_but_under_cap_is_accepted_and_flagged_in_the_refine_turn(tmp_path, monkeypatch):
    import planner3d_worker.claude.prompts as prompts_mod

    monkeypatch.setattr(prompts_mod, "TRIANGLE_BUDGET", 5)  # a box has 12 faces
    engine, client, _, _ = _make(tmp_path, [reply(box_script("v1")), reply(box_script("v2"))])
    produced, _ = _run(engine, tmp_path)
    assert len(produced) == 4
    text = _last_user_text(client.calls[1])
    assert "Triangle count: 12" in text and "over the 5 triangle budget" in text and "Parts (name" in text


def test_a_glb_with_a_huge_embedded_image_is_not_decoded_by_the_parent(tmp_path):
    import numpy as np
    from PIL import Image as PILImage

    mesh = trimesh.creation.box(extents=(1.2, 0.75, 0.6))
    mesh.apply_translation((0, 0.375, 0))
    big = PILImage.new("1", (12000, 12000))  # 144 MP once decoded, small as a PNG
    mesh.visual = trimesh.visual.TextureVisuals(uv=np.zeros((len(mesh.vertices), 2)), material=trimesh.visual.material.PBRMaterial(baseColorTexture=big))
    glb = mesh.export(file_type="glb")

    class OneShot(FakeRunner):
        def __call__(self, src, work_dir, limits):
            work_dir = Path(work_dir)
            work_dir.mkdir(parents=True, exist_ok=True)
            (work_dir / "model.glb").write_bytes(glb)
            return RunResult(ok=True, glb=work_dir / "model.glb", stderr_tail="", seconds=0.1, reason=None, glb_bytes=glb)

    client = FakeClient([reply(box_script("v1")), reply(box_script("v2"))])
    engine = ClaudeProceduralEngine(client=client, routing=_routing(tmp_path), ledger=Ledger(tmp_path / "l.jsonl"), run_script=OneShot())
    import tracemalloc

    tracemalloc.start()
    produced, _ = _run(engine, tmp_path)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert len(produced) == 4
    assert peak < 100 * 1024 * 1024


def test_one_extra_attempt_rescues_a_run_with_one_good_version(tmp_path):
    # 1 failed + 1 rejected + 1 good is still only one good: needs the extra one
    engine2, client2, _, _ = _make(tmp_path, [reply(box_script("FAIL")), reply(box_script("v2")), reply(box_script("v3"))])
    produced, _ = _run(engine2, tmp_path)
    assert len(client2.calls) == 3 and len(produced) == 4
    with pytest.raises(EngineFailure):  # not a second extra: 4 failures in a row stop at max_versions + 1
        _run(_make(tmp_path, [reply(box_script("FAIL"))] * 4)[0], tmp_path)


def test_no_extra_attempt_when_the_time_budget_is_spent(tmp_path):
    engine, client, _, _ = _make(tmp_path, [reply(box_script("FAIL")), reply(box_script("v2")), reply(box_script("v3"))])
    engine.time_budget_s = 0.0
    with pytest.raises(EngineFailure):
        _run(engine, tmp_path)
    assert len(client.calls) == 2


def test_debug_trail_is_written_per_version_and_never_returned(tmp_path):
    engine, client, _, _ = _make(
        tmp_path,
        [reply("import subprocess\n# BOX 1 1 1"), reply(box_script("v2")), reply(box_script("v3"))],
        routing=_routing(tmp_path, default_versions=3),
    )
    produced, out = _run(engine, tmp_path)
    assert "subprocess" in (out / "trail-1" / "response.txt").read_text()
    assert "rejected" in (out / "trail-1" / "error.txt").read_text()
    assert (out / "trail-2" / "response.txt").exists() and not (out / "trail-2" / "error.txt").exists()
    assert all(n.startswith("candidate-") for n, _r in produced)


def test_first_turn_carries_the_measured_photo_colours(tmp_path):
    engine, client, _, _ = _make(tmp_path, [reply(box_script("v1")), reply(box_script("v2"))])
    _run(engine, tmp_path)
    text = "\n".join(b["text"] for b in client.calls[0]["messages"][0]["content"] if b["type"] == "text")
    assert "Photo finish colours (sRGB hex, linear rgb): #c80a0a" in text


def test_planted_symlinks_in_the_work_dir_never_redirect_the_trail(tmp_path):
    canary = tmp_path / "canary.txt"
    canary.write_text("UNTOUCHED")

    class Planter(FakeRunner):
        def __call__(self, src, work_dir, limits):
            work_dir = Path(work_dir)
            work_dir.mkdir(parents=True, exist_ok=True)
            for name in ("error.txt", "response.txt"):
                (work_dir / name).symlink_to(canary)
            return RunResult(ok=False, glb=None, stderr_tail="Traceback: planted", seconds=0.1, reason="exit")

    client = FakeClient([reply(box_script("v1")), reply(box_script("v2")), reply(box_script("v3"))])
    engine = ClaudeProceduralEngine(client=client, routing=_routing(tmp_path, default_versions=3), ledger=Ledger(tmp_path / "l.jsonl"), run_script=Planter())
    with pytest.raises(EngineFailure):
        _run(engine, tmp_path)
    assert canary.read_text() == "UNTOUCHED"
    out = tmp_path / "out"
    assert "planted" in (out / "trail-1" / "error.txt").read_text()
    assert (out / "trail-1" / "response.txt").exists()


def test_an_existing_trail_dir_fails_that_version_instead_of_being_reused(tmp_path):
    engine, client, _, _ = _make(tmp_path, [reply(box_script("v1")), reply(box_script("v2")), reply(box_script("v3"))])
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "trail-1").mkdir()
    produced, out = _run(engine, tmp_path)  # v1 is dropped, v2 + v3 are good
    assert len(produced) == 4
    assert not list((out / "trail-1").iterdir())


def test_a_model_over_the_render_budget_is_decimated_before_rendering(tmp_path, monkeypatch):
    import planner3d_worker.engines.claude_procedural as mod

    monkeypatch.setattr(mod, "RENDER_FACES", 6)  # a box has 12
    seen = []
    real = mod.render_views
    monkeypatch.setattr(mod, "render_views", lambda scene, **k: seen.append(sum(len(g.faces) for g in scene.geometry.values())) or real(scene, **k))
    engine, _, _, _ = _make(tmp_path, [reply(box_script("v1")), reply(box_script("v2"))])
    _run(engine, tmp_path)
    assert seen and all(n <= 6 for n in seen)
