#!/usr/bin/env python
"""Runs INSIDE the dedicated STT venv (``~/foundryx-stt/venv``, built by
``scripts/setup_stt_venv.sh``) - never inside the backend's own venv. mlx runs
on Metal and needs its own dependency set (a different Python version and
package set than the backend), so this is exec'd as a SUBPROCESS by
``mlx_local.py``, not imported: a crash in here must never take the worker
process down (S3 plan §3.1).

Invocation: ``python mlx_runner.py <audio_path> <model>``.

Prints exactly ONE line of JSON to stdout on success:
``{"language": <str|null>, "segments": [{"start_ms": int, "end_ms": int,
"text": str}, ...]}``. Anything else on stdout/stderr is diagnostic only -
the driver treats a non-zero exit as failure and reads stderr for the tail.

``condition_on_previous_text=False`` and ``no_speech_threshold`` are both set
because unconditioned generation with the default threshold hallucinated
repeated text into trailing silence on the S1 run-7 evidence audio.
"""
from __future__ import annotations

import json
import sys

# whisper's own default; keeps quiet trailing audio from being transcribed
# as speech. The live evidence run (S3 plan, captain's step) is what proves
# this value on real meeting audio - nothing here is tuned against a
# fabricated sample.
NO_SPEECH_THRESHOLD = 0.6


def main(argv: list) -> int:
    if len(argv) != 3:
        print("usage: mlx_runner.py <audio_path> <model>", file=sys.stderr)
        return 2
    audio_path, model = argv[1], argv[2]

    import mlx_whisper  # only importable inside the dedicated STT venv

    result = mlx_whisper.transcribe(
        audio_path,
        path_or_hf_repo=model,
        condition_on_previous_text=False,
        no_speech_threshold=NO_SPEECH_THRESHOLD,
    )

    segments = []
    for seg in result.get("segments", []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        segments.append(
            {
                "start_ms": int(round(float(seg["start"]) * 1000)),
                "end_ms": int(round(float(seg["end"]) * 1000)),
                "text": text,
            }
        )

    print(json.dumps({"language": result.get("language"), "segments": segments}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
