"""Plan 72 deploy plumbing: AUTOCOUNT_PROJECT_REGISTRATIONS_FEED_BOOKS reaches prod.

The compose backend env block is an explicit allow-list (no env_file) and the
deploy workflow writes `.env` from ENV_CONTENT, so a setting missing from
either never reaches the container. Mirrors AC-63-15.
"""
from __future__ import annotations

from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).resolve().parents[2]
VAR = "AUTOCOUNT_PROJECT_REGISTRATIONS_FEED_BOOKS"


def test_config_default_is_db3():
    assert Settings.model_fields["autocount_project_registrations_feed_books"].default == "db3"


def test_compose_carries_the_env_line_in_the_shared_backend_env_block():
    lines = (ROOT / "docker-compose.yml").read_text().splitlines()
    want = f"  {VAR}: ${{{VAR}:-db3}}"
    assert want in lines
    anchor = lines.index("x-backend-env: &backend-env")
    services = next(i for i, ln in enumerate(lines) if ln == "services:")
    assert anchor < lines.index(want) < services


def test_deploy_env_content_carries_the_variable_with_a_db3_default():
    text = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    want = f"{VAR}=${{{{ vars.{VAR} || 'db3' }}}}"
    assert want in text
    assert text.index("ENV_CONTENT: |") < text.index(want)
