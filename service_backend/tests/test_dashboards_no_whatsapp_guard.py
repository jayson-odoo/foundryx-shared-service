"""AI dashboard builder S1 (SS) red tests: no WhatsApp path (S-19).

The dashboards service must stay out of the omnichannel module and must not register workflow triggers or
actions (a workflow node could otherwise push a dashboard to WhatsApp).
"""
from __future__ import annotations

import re
from pathlib import Path

MODULES = Path(__file__).resolve().parents[1] / "modules"


def test_dashboards_module_exists():
    assert (MODULES / "dashboards" / "manifest.json").is_file()
    assert (MODULES / "dashboards" / "__init__.py").is_file()


def test_omnichannel_never_imports_dashboards():
    assert (MODULES / "dashboards").is_dir(), "guard is meaningless until the module exists"
    pattern = re.compile(r"^\s*(from|import)\s+modules\.dashboards\b|^\s*from\s+modules\s+import\s+.*\bdashboards\b", re.M)
    offenders = [str(p.relative_to(MODULES)) for p in (MODULES / "omnichannel").rglob("*.py")
                 if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
    loose = [str(p.relative_to(MODULES)) for p in (MODULES / "omnichannel").rglob("*.py")
             if "modules.dashboards" in p.read_text(encoding="utf-8")]
    assert loose == []


def test_dashboards_does_not_import_omnichannel_either():
    base = MODULES / "dashboards"
    assert base.is_dir()
    offenders = [str(p.relative_to(MODULES)) for p in base.rglob("*.py")
                 if "modules.omnichannel" in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_no_workflow_trigger_or_action_starts_with_dashboard(dash_module_loaded):
    from app.workflow_engine import registry

    keys = [t.key for t in registry.list_triggers()] + [a.key for a in registry.list_actions()]
    assert keys, "workflow registry should not be empty"
    assert [k for k in keys if k.lower().startswith("dashboard")] == []
    assert not any(getattr(d, "module", "") == "dashboards" for d in registry.list_triggers() + registry.list_actions())


import pytest  # noqa: E402


@pytest.fixture
def dash_module_loaded():
    """The module's boot hooks (if any) have run: import the package so any import-time registration happens."""
    import importlib

    importlib.import_module("modules.dashboards")
    return True
