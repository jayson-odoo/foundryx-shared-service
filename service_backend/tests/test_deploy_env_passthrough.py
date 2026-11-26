"""Deploy env passthrough guard (SS-PROJREG-FLAG-PASSTHROUGH).

The backend containers get their environment ONLY from the explicit
``x-backend-env`` allow-list in the repo-root ``docker-compose.yml`` (no
``env_file``), and the server ``.env`` is rendered by ``deploy.yml``. A
Settings field missing from either side can never be set in production:
``AUTOCOUNT_PROJECT_REGISTRATION_ENABLED`` was in neither, so the GitHub
variable had no effect and a hand edit on the server was overwritten by the
next deploy.

Parses the REAL files, like ``test_s11_compose_worker_jobs.py``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
DEPLOY_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
DEPLOY_DOC_PATH = REPO_ROOT / "DEPLOY.md"

# Admin switches the owner turns on per environment through a GitHub
# variable. Each must be rendered by deploy.yml AND passed by compose, with
# the same OFF default as app/config.py.
ADMIN_SWITCHES = ("AUTOCOUNT_PROJECT_REGISTRATION_ENABLED",)


@pytest.fixture(scope="module")
def backend_env() -> dict:
    with open(COMPOSE_PATH) as f:
        return yaml.safe_load(f)["x-backend-env"]


@pytest.fixture(scope="module")
def rendered_env() -> dict[str, str]:
    text = DEPLOY_WORKFLOW_PATH.read_text()
    block = re.search(r"ENV_CONTENT: \|\n(.*?)\n\s*with:", text, re.S)
    assert block, "deploy.yml no longer has an ENV_CONTENT block to render .env"
    return dict(re.findall(r"^\s+([A-Z][A-Z0-9_]*)=(.*)$", block.group(1), re.M))


def _settings_env_names() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


def test_every_rendered_setting_reaches_the_backend_containers(backend_env, rendered_env):
    """A Settings key deploy.yml writes into .env but compose does not pass
    is a silent no-op in production."""
    missing = sorted((set(rendered_env) & _settings_env_names()) - set(backend_env))
    assert not missing, (
        f"deploy.yml renders {missing} into .env but docker-compose.yml "
        "x-backend-env does not pass them to the containers"
    )


@pytest.mark.parametrize("name", ADMIN_SWITCHES)
def test_admin_switch_is_settable_from_a_github_variable(name, backend_env, rendered_env):
    field = name.lower()
    assert field in Settings.model_fields, f"{name} is not a Settings field"
    default = Settings.model_fields[field].default
    assert default is False, f"{name} must default OFF in app/config.py"

    assert backend_env.get(name) == f"${{{name}:-false}}", (
        f"docker-compose.yml x-backend-env must pass {name} with an OFF default"
    )
    assert rendered_env.get(name) == f"${{{{ vars.{name} || 'false' }}}}", (
        f"deploy.yml must render {name} from the GitHub variable, default 'false'"
    )
    assert f"`{name}`" in DEPLOY_DOC_PATH.read_text(), (
        f"DEPLOY.md variables list must mention {name}"
    )
