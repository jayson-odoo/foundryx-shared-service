"""Caption -> Whisper-segment speaker assignment (S3 plan §3.2).

Pure function, no I/O: ``assign_speakers(segments, captions, start_epoch)``.
The caller (``jobs.py``) owns reading ``events.jsonl`` and turning it into
``CaptionEvent`` rows; everything here is timing arithmetic, unit-testable
with no fixtures.

Text similarity is deliberately NOT used - names ride TIME. Captions and
Whisper disagree on wording BY DESIGN (that is why the meeting is
transcribed at all), so matching on text would only ever be wrong.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from . import SttSegment

# A caption's approximated span floors at this width (seconds) even when the
# previous caption landed less than this long ago - Meet can finalize two
# short blocks back-to-back, and a near-zero interval would never overlap
# anything.
MIN_SPAN_S = 2.0

# A Whisper segment that overlaps no caption interval is still assigned the
# NEAREST caption, but only within this many milliseconds - past this, a
# guess is worse than no name at all (AC-S3-2).
NEAREST_WITHIN_MS = 15_000.0


@dataclass
class CaptionEvent:
    """One finalized caption block, as read from ``events.jsonl``."""

    ts: float
    speaker: str


@dataclass
class _Interval:
    start_ms: float
    end_ms: float
    speaker: str


def _intervals(captions: Sequence[CaptionEvent], start_epoch: float) -> List[_Interval]:
    """Caption events -> time spans, in ms relative to ``start_epoch`` -
    ORDINARILY non-overlapping, but not always: when the 2 s floor engages
    (two captions finalized less than ``MIN_SPAN_S`` apart) this interval's
    start is pulled back to ``ts - MIN_SPAN_S``, which can reach earlier than
    the PREVIOUS interval's own end and overlap it. ``assign_speakers`` picks
    whichever interval overlaps a segment MOST, and on an exact tie keeps the
    first found - chronologically earliest, since this list is built in
    caption order - rather than the last.

    Caption i's span ends at its own ``ts`` and starts at caption i-1's
    ``ts`` - except the first caption, whose start is ``max(recording start,
    ts - MIN_SPAN_S)``, and any caption whose predecessor landed less than
    ``MIN_SPAN_S`` ago, whose start is pulled back to ``ts - MIN_SPAN_S`` (the
    2 s floor)."""
    ordered = sorted(captions, key=lambda c: c.ts)
    intervals: List[_Interval] = []
    prev_ts: Optional[float] = None
    for cap in ordered:
        floor_ts = cap.ts - MIN_SPAN_S
        if prev_ts is None:
            start_ts = max(start_epoch, floor_ts)
        else:
            start_ts = min(prev_ts, floor_ts)
        intervals.append(
            _Interval(
                start_ms=(start_ts - start_epoch) * 1000.0,
                end_ms=(cap.ts - start_epoch) * 1000.0,
                speaker=cap.speaker,
            )
        )
        prev_ts = cap.ts
    return intervals


def _overlap_ms(seg_start: float, seg_end: float, interval: _Interval) -> float:
    return min(seg_end, interval.end_ms) - max(seg_start, interval.start_ms)


def _distance_ms(seg_start: float, seg_end: float, interval: _Interval) -> float:
    if seg_end < interval.start_ms:
        return interval.start_ms - seg_end
    if seg_start > interval.end_ms:
        return seg_start - interval.end_ms
    return 0.0  # already overlapping


def assign_speakers(
    segments: Sequence[SttSegment],
    captions: Sequence[CaptionEvent],
    start_epoch: float,
) -> List[Optional[str]]:
    """One speaker name (or ``None``) per segment, same order as ``segments``.

    - The caption interval that overlaps a segment MOST wins.
    - No overlap -> the nearest caption interval, but only within
      ``NEAREST_WITHIN_MS``.
    - Neither -> ``None`` (rendered as "Speaker" later; never a guess).
    """
    if not captions:
        return [None] * len(segments)

    intervals = _intervals(captions, start_epoch)
    result: List[Optional[str]] = []
    for seg in segments:
        best_overlap = 0.0
        best_speaker: Optional[str] = None
        for interval in intervals:
            overlap = _overlap_ms(seg.start_ms, seg.end_ms, interval)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = interval.speaker
        if best_speaker is not None:
            result.append(best_speaker)
            continue

        nearest_speaker: Optional[str] = None
        nearest_distance: Optional[float] = None
        for interval in intervals:
            distance = _distance_ms(seg.start_ms, seg.end_ms, interval)
            if nearest_distance is None or distance < nearest_distance:
                nearest_distance = distance
                nearest_speaker = interval.speaker
        if nearest_distance is not None and nearest_distance <= NEAREST_WITHIN_MS:
            result.append(nearest_speaker)
        else:
            result.append(None)
    return result
