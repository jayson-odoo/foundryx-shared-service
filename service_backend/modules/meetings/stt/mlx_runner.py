#!/usr/bin/env python
"""Runs INSIDE the dedicated STT venv (``~/foundryx-stt/venv``, built by
``scripts/setup_stt_venv.sh``) - never inside the backend's own venv. mlx runs
on Metal and needs its own dependency set (a different Python version and
package set than the backend), so this is exec'd as a SUBPROCESS by
``mlx_local.py``, not imported: a crash in here must never take the worker
process down (S3 plan §3.1).

Invocation: ``python mlx_runner.py <audio_path> <model> [chunk_s]
[languages_csv]`` - ``chunk_s`` defaults to 30 and ``languages_csv`` defaults
to "en,ms,zh", so a manual invocation with just the first two args still
works.

Chunked design (S3 code-switch fix, 2026-09-01): a single
``mlx_whisper.transcribe()`` call over the WHOLE file detects language ONCE,
from the first ~30s, and decodes the rest of the recording - a Malay/Chinese
passage in an otherwise-English meeting - as garbled English. This runner
instead ffmpeg-segments the audio into ``chunk_s``-second wav chunks and
detects language PER CHUNK, constrained to an allowlist (``languages_csv``)
because a quiet or silent chunk misdetects as an unrelated language (es/pt on
the eval recording) without one; the pilot's meetings are only ever
en/ms/zh. Each chunk is then transcribed forcing its own detected language,
so a code-switched meeting comes back verbatim instead of locked to one
language for the whole file.

Prints exactly ONE line of JSON to stdout on success:
``{"language": <str|null>, "segments": [{"start_ms": int, "end_ms": int,
"text": str, "language": str}, ...]}``. The top-level ``language`` is the
majority chunk language (ties broken by first occurrence); every segment
carries the detected language of the chunk it came from. Anything else on
stdout/stderr is diagnostic only - the driver treats a non-zero exit as
failure and reads stderr for the tail.

``condition_on_previous_text=False`` and ``no_speech_threshold`` are both set
on every transcribe call because unconditioned generation with the default
threshold hallucinated repeated text into trailing silence on the S1 run-7
evidence audio. Consecutive identical segments (whisper's repetition-loop
failure mode, e.g. "I don't know" x5) are collapsed into one before output.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

# whisper's own default; keeps quiet trailing audio from being transcribed
# as speech. The live evidence run (S3 plan, captain's step) is what proves
# this value on real meeting audio - nothing here is tuned against a
# fabricated sample.
NO_SPEECH_THRESHOLD = 0.6

DEFAULT_CHUNK_S = 30
DEFAULT_LANGUAGES = "en,ms,zh"

USAGE = "usage: mlx_runner.py <audio_path> <model> [chunk_s] [languages_csv]"


# ── Pure helpers (no mlx import - unit-testable from the backend venv) ─────


def parse_languages(languages_csv: str) -> List[str]:
    """``"en,ms,zh"`` -> ``["en", "ms", "zh"]``. Blank entries dropped."""
    return [item.strip() for item in languages_csv.split(",") if item.strip()]


def pick_language(probs: Dict[str, float], allowlist: List[str]) -> str:
    """The allowlist member with the highest probability, missing keys
    treated as 0.0. This is what coerces a quiet chunk's top-1 (es, pt, ...)
    into an in-allowlist language rather than propagating junk."""
    return max(allowlist, key=lambda lang: probs.get(lang, 0.0))


def chunk_offsets_ms(durations_ms: List[int]) -> List[int]:
    """Cumulative offset (ms) BEFORE each chunk, built from each chunk's REAL
    measured duration (ffprobe) - never ``i * chunk_s * 1000``: the last
    chunk is shorter than ``chunk_s``, and trusting the nominal length is
    what produced overlapping offsets in the eval's first chunked attempt."""
    offsets: List[int] = []
    total = 0
    for duration_ms in durations_ms:
        offsets.append(total)
        total += duration_ms
    return offsets


def build_segment(
    raw_segment: dict, offset_ms: int, chunk_end_ms: int, language: str
) -> Optional[dict]:
    """One whisper segment (``start``/``end`` in seconds, relative to its
    chunk) converted to an absolute-ms segment tagged with the chunk's
    detected language. Returns ``None`` for empty text, a segment whose
    start lies at/after the chunk's own end (a boundary artifact), or a
    segment that is zero-length once ``end_ms`` is clamped to the chunk's
    own end (it would otherwise leak downstream and get logged as an
    invalid provider segment). ``end_ms`` is clamped so a segment never
    bleeds into the next chunk's time range."""
    text = (raw_segment.get("text") or "").strip()
    if not text:
        return None
    start_ms = offset_ms + int(round(float(raw_segment["start"]) * 1000))
    if start_ms >= chunk_end_ms:
        return None
    end_ms = offset_ms + int(round(float(raw_segment["end"]) * 1000))
    end_ms = min(end_ms, chunk_end_ms)
    if end_ms <= start_ms:
        return None
    return {"start_ms": start_ms, "end_ms": end_ms, "text": text, "language": language}


def collapse_repetition(segments: List[dict]) -> List[dict]:
    """Merge RUNS of consecutive segments whose text is identical after
    ``.strip().casefold()`` AND whose ``language`` also matches, into one,
    keeping the first segment's ``start_ms``/``language`` and the last
    segment's ``end_ms``. Requiring the language match too stops two
    segments that merely share text across a chunk (and therefore language)
    boundary from merging - a repetition loop never actually changes
    language mid-run. Kills whisper's repetition-loop failure mode without
    touching two identical lines that are not adjacent (a real, distinct
    repeat)."""
    collapsed: List[dict] = []
    for segment in segments:
        if (
            collapsed
            and collapsed[-1]["language"] == segment["language"]
            and collapsed[-1]["text"].strip().casefold() == segment["text"].strip().casefold()
        ):
            merged = dict(collapsed[-1])
            merged["end_ms"] = segment["end_ms"]
            collapsed[-1] = merged
        else:
            collapsed.append(dict(segment))
    return collapsed


def majority_language(picked_languages: List[str]) -> Optional[str]:
    """The most common entry, ties broken by first occurrence. ``None`` for
    an empty list (no chunks - never happens on a real audio file, but keeps
    this total)."""
    if not picked_languages:
        return None
    counts: Dict[str, int] = {}
    order: List[str] = []
    for lang in picked_languages:
        if lang not in counts:
            counts[lang] = 0
            order.append(lang)
        counts[lang] += 1
    best = order[0]
    for lang in order[1:]:
        if counts[lang] > counts[best]:
            best = lang
    return best


# ── mlx-touching helpers (imported only here, so this module still imports
# top-level in the backend venv for the pure-function tests above) ─────────


def _load_model(model_name: str):
    import mlx.core as mx
    from mlx_whisper.transcribe import ModelHolder

    # Share transcribe()'s own model cache (same repo, same fp16 dtype) so
    # detection and transcription use ONE model copy. A separate
    # load_models.load_model() call held a SECOND full large-v3 copy (and at
    # float32, twice the size of transcribe's fp16 one): on the 16 GB pilot
    # host that swap-thrashed a 6.6 min recording from ~1 min to 25 min.
    # ModelHolder is internal API, acceptable because mlx-whisper is pinned
    # (==0.4.3) in the dedicated venv (R6).
    return ModelHolder.get_model(model_name, mx.float16)


def _detect_language(model, wav_path: Path, allowlist: List[str]) -> str:
    # ``A.N_FRAMES`` is a fixed 30s worth of mel frames - detection only ever
    # reads the first ~30s of whatever ``wav_path`` is, so a ``chunk_s``
    # above 30 detects language from a PREFIX of the chunk, not the whole
    # thing. Not a problem at the default (30) or below.
    import mlx.core as mx
    from mlx_whisper import audio as A
    from mlx_whisper import decoding

    mel = A.log_mel_spectrogram(str(wav_path), n_mels=model.dims.n_mels)
    # axis=-2 is load-bearing: the default axis pads the wrong dimension and
    # breaks the encoder (captain's prototype, S3 code-switch fix).
    mel = A.pad_or_trim(mel, A.N_FRAMES, axis=-2)
    # Matches upstream transcribe()'s own dtype - avoids running the encoder
    # pass at fp32 against an fp16 model.
    mel = mel.astype(mx.float16)
    _, probs_list = decoding.detect_language(model, mel)
    probs = probs_list[0] if isinstance(probs_list, list) else probs_list
    return pick_language(probs, allowlist)


def _transcribe_chunk(wav_path: Path, model: str, language: str) -> dict:
    import mlx_whisper

    return mlx_whisper.transcribe(
        str(wav_path),
        path_or_hf_repo=model,
        language=language,
        condition_on_previous_text=False,
        no_speech_threshold=NO_SPEECH_THRESHOLD,
    )


def _ffprobe_duration_ms(wav_path: Path) -> int:
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(wav_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or "", file=sys.stderr)
        raise

    raw = completed.stdout.strip()
    try:
        return int(round(float(raw) * 1000))
    except ValueError as exc:
        print(
            f"ffprobe produced an unparseable duration for {wav_path}: {raw!r}",
            file=sys.stderr,
        )
        raise ValueError(f"unparseable ffprobe duration: {raw!r}") from exc


def _segment_audio(audio_path: str, chunk_dir: Path, chunk_s: int) -> List[Path]:
    # %05d, not %03d: at a short chunk_s (5s is real - S3 review) a long
    # recording produces more than 999 chunks, and lexicographic sort on a
    # 3-digit name wraps back to "c000.wav" after "c999.wav" and scrambles
    # chunk order.
    pattern = chunk_dir / "c%05d.wav"
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                audio_path,
                "-f",
                "segment",
                "-segment_time",
                str(chunk_s),
                "-c:a",
                "pcm_s16le",
                "-ar",
                "16000",
                "-ac",
                "1",
                str(pattern),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or "", file=sys.stderr)
        raise
    return sorted(chunk_dir.glob("c*.wav"))


def main(argv: list) -> int:
    if not (3 <= len(argv) <= 5):
        print(USAGE, file=sys.stderr)
        return 2
    audio_path, model = argv[1], argv[2]

    chunk_s_raw = argv[3] if len(argv) > 3 else str(DEFAULT_CHUNK_S)
    try:
        chunk_s = int(chunk_s_raw)
    except ValueError:
        chunk_s = None
    if chunk_s is None or chunk_s <= 0:
        print(f"{USAGE} (chunk_s must be a positive integer)", file=sys.stderr)
        return 2

    languages_csv = argv[4] if len(argv) > 4 else DEFAULT_LANGUAGES
    allowlist = parse_languages(languages_csv)
    if not allowlist:
        print(f"{USAGE} (languages_csv must name at least one language)", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            chunk_paths = _segment_audio(audio_path, Path(tmpdir), chunk_s)
        except subprocess.CalledProcessError:
            return 1

        if not chunk_paths:
            print("ffmpeg produced no chunks", file=sys.stderr)
            return 1

        try:
            durations_ms = [_ffprobe_duration_ms(path) for path in chunk_paths]
        except (subprocess.CalledProcessError, ValueError):
            return 1
        offsets_ms = chunk_offsets_ms(durations_ms)

        model_handle = _load_model(model)  # load ONCE per process

        all_segments: List[dict] = []
        picked_languages: List[str] = []
        for chunk_path, offset_ms, duration_ms in zip(chunk_paths, offsets_ms, durations_ms):
            language = _detect_language(model_handle, chunk_path, allowlist)
            picked_languages.append(language)

            raw = _transcribe_chunk(chunk_path, model, language)
            chunk_end_ms = offset_ms + duration_ms
            for raw_segment in raw.get("segments", []):
                segment = build_segment(raw_segment, offset_ms, chunk_end_ms, language)
                if segment is not None:
                    all_segments.append(segment)

    segments = collapse_repetition(all_segments)
    language = majority_language(picked_languages)

    print(json.dumps({"language": language, "segments": segments}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
