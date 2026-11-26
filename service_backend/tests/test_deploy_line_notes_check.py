"""Plan 73 B2: the blue/green deploy runs the line notes check in the NEW backend container after the health wait and
before the Caddy swap, and aborts the new color when it fails (the old color keeps serving)."""
from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "blue_green_deploy.sh"


def test_the_check_runs_before_the_swap_and_aborts_the_new_color():
    text = SCRIPT.read_text()
    cmd = "python -m modules.autocount.write_back.admin check-line-notes"
    assert cmd in text
    health = text.index("not healthy after")
    check = text.index(cmd)
    swap = text.index("# 4. Swap Caddy")
    assert health < check < swap
    assert 'abort_new_color backend "AutoCount line notes check failed"' in text[check:swap]
    assert 'docker exec "$NEW_BACKEND_CID"' in text[check - 80:check + 40] or 'docker exec "$NEW_BACKEND_CID"' in text[:check][-200:]
