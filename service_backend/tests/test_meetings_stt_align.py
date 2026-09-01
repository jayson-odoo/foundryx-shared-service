"""``assign_speakers`` - pure timing arithmetic, no fixtures needed (S3 plan
§3.2, AC-S3-2)."""
import pytest

from modules.meetings.stt import SttSegment
from modules.meetings.stt.align import CaptionEvent, assign_speakers

START = 1_000.0  # recording start epoch


def test_a_segment_inside_one_captions_span_gets_that_speaker():
    # Caption span is [3000, 5000) (ts=5000ms, floored to a 2000ms width) -
    # the segment sits FULLY inside it, so this exercises the overlap branch,
    # not the nearest-caption fallback (a segment merely touching the span's
    # edge falls through to that instead - see the test right below).
    captions = [CaptionEvent(ts=START + 5.0, speaker="Alice")]
    segments = [SttSegment(start_ms=3500, end_ms=4500, text="hello")]

    assert assign_speakers(segments, captions, START) == ["Alice"]


def test_a_segment_only_touching_a_captions_span_boundary_uses_nearest():
    """Zero overlap (the segment ENDS exactly where the caption span starts)
    still resolves via the nearest-caption fallback, at distance 0 - not the
    overlap branch, which requires overlap > 0."""
    captions = [CaptionEvent(ts=START + 5.0, speaker="Alice")]  # span [3000, 5000)
    segments = [SttSegment(start_ms=1000, end_ms=3000, text="hello")]

    assert assign_speakers(segments, captions, START) == ["Alice"]


def test_the_caption_with_the_most_overlap_wins():
    captions = [
        CaptionEvent(ts=START + 4.0, speaker="Alice"),  # span ~[2000, 4000)
        CaptionEvent(ts=START + 10.0, speaker="Bob"),  # span [4000, 10000)
    ]
    # Segment mostly inside Bob's span (4500-9000) but nudges into Alice's.
    segments = [SttSegment(start_ms=3800, end_ms=9000, text="mixed")]

    assert assign_speakers(segments, captions, START) == ["Bob"]


def test_a_segment_with_no_overlap_takes_the_nearest_caption_within_15s():
    captions = [CaptionEvent(ts=START + 5.0, speaker="Alice")]  # span [3000, 5000)
    # Starts 10s after the caption interval ends (5000ms) - within 15s.
    segments = [SttSegment(start_ms=15_000, end_ms=16_000, text="later")]

    assert assign_speakers(segments, captions, START) == ["Alice"]


def test_a_segment_more_than_15s_from_any_caption_gets_no_speaker():
    captions = [CaptionEvent(ts=START + 5.0, speaker="Alice")]  # span [3000, 5000)
    # 20s past the caption interval's end - past the 15s reach.
    segments = [SttSegment(start_ms=25_000, end_ms=26_000, text="way later")]

    assert assign_speakers(segments, captions, START) == [None]


def test_no_captions_at_all_leaves_every_segment_unassigned():
    segments = [
        SttSegment(start_ms=0, end_ms=1000, text="a"),
        SttSegment(start_ms=1000, end_ms=2000, text="b"),
    ]

    assert assign_speakers(segments, [], START) == [None, None]


def test_an_empty_segment_list_returns_an_empty_list():
    captions = [CaptionEvent(ts=START + 5.0, speaker="Alice")]

    assert assign_speakers([], captions, START) == []
    assert assign_speakers([], [], START) == []


def test_captions_less_than_two_seconds_apart_still_get_a_two_second_floor():
    """A direct check of the interval builder: without the floor, two captions
    0.3s apart would produce a ~300ms span that could overlap almost nothing
    - the floor guarantees at least 2000ms."""
    from modules.meetings.stt.align import _intervals

    captions = [
        CaptionEvent(ts=START + 10.0, speaker="Alice"),
        CaptionEvent(ts=START + 10.3, speaker="Bob"),
    ]

    intervals = _intervals(captions, START)

    bob = next(i for i in intervals if i.speaker == "Bob")
    assert bob.end_ms - bob.start_ms >= 2000.0
    assert bob.end_ms == pytest.approx(10_300.0)


def test_the_first_captions_start_never_goes_before_the_recording_start():
    # First caption at ts=0.5s into the recording - ts-2s would be negative;
    # the interval must clamp to the recording start (0ms), not -1500ms.
    from modules.meetings.stt.align import _intervals

    captions = [CaptionEvent(ts=START + 0.5, speaker="Alice")]
    segments = [SttSegment(start_ms=0, end_ms=400, text="opening")]

    assert _intervals(captions, START)[0].start_ms == 0  # the clamp itself, pinned
    assert assign_speakers(segments, captions, START) == ["Alice"]
