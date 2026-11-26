import pytest

from planner3d_worker.runner import JobTimeout, MemoryCapExceeded, run_capped
from planner3d_worker.tests import runner_targets as t


def test_ac_s3_21_run_capped_returns_result_peak_seconds():
    result, peak, seconds = run_capped(t.add, (2, 3), rss_cap_mb=2000, timeout_s=30)
    assert result == 5
    assert peak > 0
    assert 0 <= seconds < 30


def test_ac_s3_21_memory_cap_kills_child():
    with pytest.raises(MemoryCapExceeded):
        run_capped(t.hog_memory, (300,), rss_cap_mb=100, timeout_s=30)


def test_ac_s3_21_timeout_raises_job_timeout():
    with pytest.raises(JobTimeout):
        run_capped(t.sleeper, (30,), rss_cap_mb=2000, timeout_s=1)
