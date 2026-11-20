"""Pure helpers in ``modules/meetings/stt/mlx_runner.py`` (S3 code-switch
fix, 2026-09-01) - the per-chunk language pick, offset accumulation,
segment clamping and repetition collapse that make a code-switched meeting
transcribe verbatim instead of locked to one language for the whole file.

Every function under test here has NO mlx import, so this runs in the
backend venv exactly like any other unit test - the mlx-touching code in the
same module (``_load_model``, ``_detect_language``, ``_transcribe_chunk``)
only ever runs inside the dedicated STT venv and is out of scope here.
``_ffprobe_duration_ms`` and ``_segment_audio`` DO import top-level (only
``subprocess``) so their error-handling is covered here too, with a faked
``subprocess.run``/``subprocess.CalledProcessError``.
"""
import json
import subprocess
from pathlib import Path

import pytest

from modules.meetings.stt import mlx_runner


# ── parse_languages ─────────────────────────────────────────────────────


def test_parse_languages_splits_on_comma_and_drops_blanks():
    assert mlx_runner.parse_languages("en,ms,zh") == ["en", "ms", "zh"]
    assert mlx_runner.parse_languages(" en , ms ,, zh ") == ["en", "ms", "zh"]


# ── pick_language ───────────────────────────────────────────────────────


def test_pick_language_zh_beats_en_when_zh_prob_is_higher():
    probs = {"zh": 0.565, "ms": 0.10, "en": 0.05}
    assert mlx_runner.pick_language(probs, ["en", "ms", "zh"]) == "zh"


def test_pick_language_coerces_an_out_of_allowlist_top1_to_the_best_in_list():
    """The eval recording's quiet chunks top-1'd es/pt - neither is in the
    allowlist, so the pick must still land on an allowlist member."""
    probs = {"es": 0.341, "pt": 0.841, "en": 0.02, "ms": 0.01, "zh": 0.01}
    assert mlx_runner.pick_language(probs, ["en", "ms", "zh"]) == "en"


def test_pick_language_treats_a_missing_key_as_zero():
    probs = {"zh": 0.9}
    assert mlx_runner.pick_language(probs, ["en", "ms", "zh"]) == "zh"
    probs_empty: dict = {}
    # every allowlist member missing -> the first one wins the max() tie
    assert mlx_runner.pick_language(probs_empty, ["en", "ms", "zh"]) == "en"


# ── chunk_offsets_ms ─────────────────────────────────────────────────────


def test_chunk_offsets_ms_accumulates_real_durations_not_nominal_chunk_s():
    # Real ffmpeg-cut chunks drift off the nominal 30_000ms boundary.
    durations_ms = [29_800, 30_150, 29_950]
    assert mlx_runner.chunk_offsets_ms(durations_ms) == [0, 29_800, 59_950]


def test_chunk_offsets_ms_empty_list():
    assert mlx_runner.chunk_offsets_ms([]) == []


# ── build_segment ────────────────────────────────────────────────────────


def test_build_segment_converts_seconds_to_absolute_ms_with_offset():
    raw = {"start": 1.0, "end": 2.5, "text": "hello"}
    seg = mlx_runner.build_segment(raw, offset_ms=30_000, chunk_end_ms=60_000, language="en")
    assert seg == {"start_ms": 31_000, "end_ms": 32_500, "text": "hello", "language": "en"}


def test_build_segment_clamps_end_ms_to_the_chunk_end():
    raw = {"start": 28.0, "end": 31.5, "text": "runs past the chunk boundary"}
    seg = mlx_runner.build_segment(raw, offset_ms=0, chunk_end_ms=30_000, language="ms")
    assert seg["end_ms"] == 30_000


def test_build_segment_drops_a_segment_starting_at_or_after_the_chunk_end():
    raw = {"start": 30.0, "end": 31.0, "text": "boundary artifact"}
    assert mlx_runner.build_segment(raw, offset_ms=0, chunk_end_ms=30_000, language="en") is None


def test_build_segment_drops_empty_text():
    raw = {"start": 1.0, "end": 2.0, "text": "   "}
    assert mlx_runner.build_segment(raw, offset_ms=0, chunk_end_ms=30_000, language="en") is None


# ── collapse_repetition ─────────────────────────────────────────────────


def test_collapse_repetition_merges_only_consecutive_case_insensitive_matches():
    segments = [
        {"start_ms": 0, "end_ms": 500, "text": "I don't know", "language": "en"},
        {"start_ms": 500, "end_ms": 1000, "text": "I DON'T KNOW", "language": "en"},
        {"start_ms": 1000, "end_ms": 1500, "text": " i don't know ", "language": "en"},
        {"start_ms": 1500, "end_ms": 2000, "text": "actually let me think", "language": "en"},
        {"start_ms": 2000, "end_ms": 2500, "text": "I don't know", "language": "en"},
    ]
    collapsed = mlx_runner.collapse_repetition(segments)
    assert [s["text"] for s in collapsed] == [
        "I don't know",
        "actually let me think",
        "I don't know",
    ]
    assert collapsed[0]["start_ms"] == 0
    assert collapsed[0]["end_ms"] == 1500  # last of the merged run


def test_collapse_repetition_no_adjacent_duplicates_is_a_no_op():
    segments = [
        {"start_ms": 0, "end_ms": 500, "text": "hi", "language": "en"},
        {"start_ms": 500, "end_ms": 1000, "text": "there", "language": "en"},
    ]
    assert mlx_runner.collapse_repetition(segments) == segments


def test_collapse_repetition_empty_list():
    assert mlx_runner.collapse_repetition([]) == []


# ── majority_language ────────────────────────────────────────────────────


def test_majority_language_picks_the_most_common():
    assert mlx_runner.majority_language(["en", "zh", "zh", "ms"]) == "zh"


def test_majority_language_ties_break_by_first_occurrence():
    assert mlx_runner.majority_language(["ms", "en", "ms", "en"]) == "ms"


def test_majority_language_empty_list_is_none():
    assert mlx_runner.majority_language([]) is None


# ── collapse_repetition: language boundary (review S7) ──────────────────


def test_collapse_repetition_does_not_merge_identical_text_across_a_language_change():
    """A chunk boundary can hand two adjacent segments the SAME text in two
    DIFFERENT detected languages (e.g. a short acknowledgement token) - that
    must not merge, since merging would silently discard one language's
    detection."""
    segments = [
        {"start_ms": 0, "end_ms": 500, "text": "okay", "language": "en"},
        {"start_ms": 500, "end_ms": 1000, "text": "okay", "language": "ms"},
    ]
    assert mlx_runner.collapse_repetition(segments) == segments


# ── _ffprobe_duration_ms (review S2) ─────────────────────────────────────


class _FakeCompleted:
    def __init__(self, stdout="", stderr=""):
        self.stdout = stdout
        self.stderr = stderr


def test_ffprobe_duration_ms_parses_seconds_to_ms(monkeypatch):
    monkeypatch.setattr(
        mlx_runner.subprocess, "run", lambda *a, **k: _FakeCompleted(stdout="12.345\n")
    )
    assert mlx_runner._ffprobe_duration_ms(Path("chunk.wav")) == 12345


def test_ffprobe_duration_ms_prints_stderr_and_reraises_on_a_failed_probe(monkeypatch, capsys):
    def _boom(*a, **k):
        raise subprocess.CalledProcessError(1, "ffprobe", stderr="No such file or directory")

    monkeypatch.setattr(mlx_runner.subprocess, "run", _boom)

    with pytest.raises(subprocess.CalledProcessError):
        mlx_runner._ffprobe_duration_ms(Path("chunk.wav"))

    assert "No such file or directory" in capsys.readouterr().err


def test_ffprobe_duration_ms_unparseable_stdout_exits_cleanly_not_a_bare_traceback(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        mlx_runner.subprocess, "run", lambda *a, **k: _FakeCompleted(stdout="N/A\n")
    )

    with pytest.raises(ValueError, match="unparseable"):
        mlx_runner._ffprobe_duration_ms(Path("chunk.wav"))

    err = capsys.readouterr().err
    assert "unparseable" in err.lower()
    assert "N/A" in err


# ── _segment_audio (review S3: %05d, not %03d) ───────────────────────────


def test_segment_audio_uses_a_five_digit_pattern_so_1000_plus_chunks_sort_correctly(
    monkeypatch, tmp_path
):
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeCompleted()

    monkeypatch.setattr(mlx_runner.subprocess, "run", _fake_run)

    mlx_runner._segment_audio("audio.ogg", tmp_path, chunk_s=5)

    assert str(tmp_path / "c%05d.wav") in captured["cmd"]


def test_segment_audio_prints_ffmpeg_stderr_and_reraises_on_failure(monkeypatch, tmp_path, capsys):
    def _boom(*a, **k):
        raise subprocess.CalledProcessError(1, "ffmpeg", stderr="Invalid data found")

    monkeypatch.setattr(mlx_runner.subprocess, "run", _boom)

    with pytest.raises(subprocess.CalledProcessError):
        mlx_runner._segment_audio("audio.ogg", tmp_path, chunk_s=30)

    assert "Invalid data found" in capsys.readouterr().err


# ── main(): validation exits (review S1) - before ANY work ──────────────


def test_main_exits_2_on_an_empty_allowlist_before_doing_any_work(monkeypatch, capsys):
    monkeypatch.setattr(
        mlx_runner,
        "_segment_audio",
        lambda *a, **k: pytest.fail("must not run ffmpeg on a validation failure"),
    )

    code = mlx_runner.main(["mlx_runner.py", "audio.ogg", "model", "30", " , , "])

    assert code == 2
    assert "usage" in capsys.readouterr().err.lower()


def test_main_exits_2_on_a_non_integer_chunk_s_before_doing_any_work(monkeypatch, capsys):
    monkeypatch.setattr(
        mlx_runner,
        "_segment_audio",
        lambda *a, **k: pytest.fail("must not run ffmpeg on a validation failure"),
    )

    code = mlx_runner.main(["mlx_runner.py", "audio.ogg", "model", "not-a-number"])

    assert code == 2
    assert "usage" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("bad_chunk_s", ["0", "-5"])
def test_main_exits_2_on_a_non_positive_chunk_s(monkeypatch, capsys, bad_chunk_s):
    monkeypatch.setattr(
        mlx_runner,
        "_segment_audio",
        lambda *a, **k: pytest.fail("must not run ffmpeg on a validation failure"),
    )

    code = mlx_runner.main(["mlx_runner.py", "audio.ogg", "model", bad_chunk_s])

    assert code == 2
    assert "usage" in capsys.readouterr().err.lower()


def test_main_bad_argv_count_exits_2(capsys):
    code = mlx_runner.main(["mlx_runner.py", "audio.ogg"])
    assert code == 2
    assert "usage" in capsys.readouterr().err.lower()


# ── main(): full pipeline composition (review S8) ────────────────────────


def test_main_composes_the_full_pipeline_with_real_offsets_language_tags_and_collapse(
    monkeypatch, capsys, tmp_path
):
    """Every mlx-touching helper is faked; what is under test is main()'s OWN
    wiring: default chunk_s/languages, real-duration offset accumulation
    (not i * chunk_s * 1000), per-segment language tagging, repetition
    collapse, and exactly one JSON line on stdout carrying the majority
    language."""
    chunk0 = tmp_path / "c00000.wav"
    chunk1 = tmp_path / "c00001.wav"

    monkeypatch.setattr(
        mlx_runner, "_segment_audio", lambda audio_path, chunk_dir, chunk_s: [chunk0, chunk1]
    )

    durations_ms = {chunk0: 10_000, chunk1: 12_000}
    monkeypatch.setattr(mlx_runner, "_ffprobe_duration_ms", lambda path: durations_ms[path])

    load_calls = []

    def _fake_load_model(model_name):
        load_calls.append(model_name)
        return "FAKE_MODEL_HANDLE"

    monkeypatch.setattr(mlx_runner, "_load_model", _fake_load_model)

    languages = {chunk0: "en", chunk1: "zh"}
    detect_calls = []

    def _fake_detect_language(model, wav_path, allowlist):
        detect_calls.append((model, wav_path, list(allowlist)))
        return languages[wav_path]

    monkeypatch.setattr(mlx_runner, "_detect_language", _fake_detect_language)

    raw_by_chunk = {
        chunk0: {
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "hi"},
                {"start": 1.0, "end": 2.0, "text": "HI"},  # collapses into the first
            ]
        },
        chunk1: {"segments": [{"start": 0.5, "end": 1.5, "text": "you good"}]},
    }
    transcribe_calls = []

    def _fake_transcribe_chunk(wav_path, model, language):
        transcribe_calls.append((wav_path, model, language))
        return raw_by_chunk[wav_path]

    monkeypatch.setattr(mlx_runner, "_transcribe_chunk", _fake_transcribe_chunk)

    exit_code = mlx_runner.main(["mlx_runner.py", "audio.ogg", "some-model"])

    assert exit_code == 0
    assert load_calls == ["some-model"]  # loaded ONCE per process
    assert [d[2] for d in detect_calls] == [["en", "ms", "zh"], ["en", "ms", "zh"]]
    assert [t[2] for t in transcribe_calls] == ["en", "zh"]  # forced per-chunk

    out_lines = capsys.readouterr().out.strip().splitlines()
    assert len(out_lines) == 1  # exactly one JSON line
    payload = json.loads(out_lines[0])

    # chunk1's offset is chunk0's REAL duration (10_000ms), never
    # DEFAULT_CHUNK_S * 1000 (30_000ms).
    assert payload["segments"] == [
        {"start_ms": 0, "end_ms": 2000, "text": "hi", "language": "en"},
        {"start_ms": 10500, "end_ms": 11500, "text": "you good", "language": "zh"},
    ]
    # "en" and "zh" each picked once - tie broken by first occurrence.
    assert payload["language"] == "en"
