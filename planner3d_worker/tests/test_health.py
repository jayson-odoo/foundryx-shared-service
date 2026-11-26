import pytest

from planner3d_worker.health import can_start, parse_swapusage

TEXT = "total = 9216.00M  used = 7623.31M  free = 1592.69M  (encrypted)"


def test_ac_s3_20_parse_swapusage():
    used, total = parse_swapusage(TEXT)
    assert used == pytest.approx(7623.31)
    assert total == pytest.approx(9216.0)


def test_ac_s3_20_refuses_high_swap():
    ok, reason = can_start(swap_used_pct=85, free_ram_mb=8000)
    assert ok is False and reason


def test_ac_s3_20_refuses_low_free_ram():
    ok, reason = can_start(swap_used_pct=10, free_ram_mb=1000)
    assert ok is False and reason


def test_ac_s3_20_allows_healthy():
    ok, _ = can_start(swap_used_pct=50, free_ram_mb=4000)
    assert ok is True


def test_ac_s3_20_custom_thresholds():
    ok, _ = can_start(swap_used_pct=50, free_ram_mb=4000, max_swap_pct=40)
    assert ok is False
