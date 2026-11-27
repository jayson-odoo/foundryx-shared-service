"""claude-procedural red tests: spend ledger (D8)."""
import json

import pytest

from planner3d_worker.claude.ledger import Ledger, cost_usd

SONNET = {"input": 2.0, "output": 10.0, "cacheRead": 0.10}
OPUS = {"input": 4.0, "output": 20.0, "cacheRead": 0.20}


def test_cost_sonnet_bills_cache_creation_as_input():
    usage = {
        "input_tokens": 1000,
        "output_tokens": 500,
        "cache_read_input_tokens": 2000,
        "cache_creation_input_tokens": 100,
    }
    assert cost_usd(usage, SONNET) == pytest.approx((1100 * 2.0 + 500 * 10.0 + 2000 * 0.10) / 1e6)


def test_cost_opus_and_missing_keys_count_as_zero():
    assert cost_usd({"input_tokens": 1_000_000, "output_tokens": 1_000_000}, OPUS) == pytest.approx(24.0)
    assert cost_usd({}, OPUS) == 0.0


def test_missing_file_totals_zero(tmp_path):
    assert Ledger(tmp_path / "nope.jsonl").total_usd() == 0.0


def test_append_one_json_line_per_entry_and_total_sums_usd(tmp_path):
    path = tmp_path / "claude-ledger.jsonl"
    ledger = Ledger(path)
    base = {
        "at": "2026-11-27T10:00:00Z", "jobRef": "j1", "productCode": "SRTWC286-SH", "model": "m",
        "inputTokens": 10, "outputTokens": 5, "cacheReadTokens": 0,
    }
    ledger.append({**base, "usd": 1.25})
    ledger.append({**base, "usd": 0.5})
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["usd"] == 1.25
    assert ledger.total_usd() == pytest.approx(1.75)
    assert Ledger(path).total_usd() == pytest.approx(1.75)
