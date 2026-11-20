"""``run_module_migrations(engine, name)`` must migrate the engine it is given.

Today the schema/state checks run on the passed engine but Alembic's ``sqlalchemy.url`` comes from
``settings.database_url`` (``app/module_platform/migrations.py``), so a caller passing a scratch-DB engine
upgrades the .env DB (split brain). Fully faked engine and Alembic call: no Postgres.
"""

from __future__ import annotations

import pytest
from sqlalchemy.engine import URL, make_url

from app.module_platform import migrations as migrations_mod

SETTINGS_URL = "postgresql://foundryx:foundryx@localhost:5432/foundryx_service"


def _rig(monkeypatch, tmp_path, engine):
    module_dir = tmp_path / "fakemod-url"
    (module_dir / "alembic").mkdir(parents=True, exist_ok=True)
    manifest = {"module_name": "fakemod-url", "_dir": "fakemod-url"}  # no schema -> no CREATE SCHEMA
    monkeypatch.setattr(migrations_mod, "MODULES_DIR", tmp_path)
    monkeypatch.setattr(migrations_mod, "discover_manifests", lambda *a, **k: [manifest])
    monkeypatch.setattr(migrations_mod, "_migration_state", lambda *a, **k: "fresh")
    from app.config import settings

    monkeypatch.setattr(settings, "database_url", SETTINGS_URL)
    seen = []
    monkeypatch.setattr("alembic.command.upgrade", lambda cfg, rev: seen.append(cfg))
    migrations_mod.run_module_migrations(engine, "fakemod-url")
    assert len(seen) == 1
    return seen[0]


class _Dialect:
    name = "postgresql"


def _engine(url=None):
    class _Engine:
        dialect = _Dialect()

    if url is not None:
        _Engine.url = url
    return _Engine()


def _plain(url) -> str:
    return make_url(url).render_as_string(hide_password=False)


def test_alembic_targets_the_database_of_the_engine_it_was_given(monkeypatch, tmp_path):
    scratch = URL.create("postgresql", username="scratch", password="pw", host="scratch-host", port=5439,
                         database="scratch_db")
    cfg = _rig(monkeypatch, tmp_path, _engine(scratch))
    got = make_url(cfg.get_main_option("sqlalchemy.url"))
    assert (got.host, got.port, got.database) == ("scratch-host", 5439, "scratch_db"), got
    assert got.database != "foundryx_service"


def test_a_password_with_a_percent_survives_the_config_round_trip(monkeypatch, tmp_path):
    scratch = URL.create("postgresql", username="scratch", password="p%ss%25w@rd", host="scratch-host",
                         database="scratch_db")
    cfg = _rig(monkeypatch, tmp_path, _engine(scratch))  # configparser interpolation must not break or alter it
    assert _plain(cfg.get_main_option("sqlalchemy.url")) == scratch.render_as_string(hide_password=False)
    assert make_url(cfg.get_main_option("sqlalchemy.url")).password == "p%ss%25w@rd"


def test_control_an_engine_without_a_usable_url_keeps_the_settings_database(monkeypatch, tmp_path):
    cfg = _rig(monkeypatch, tmp_path, _engine())
    assert cfg.get_main_option("sqlalchemy.url") == SETTINGS_URL


def test_control_an_engine_with_a_non_url_attribute_keeps_the_settings_database(monkeypatch, tmp_path):
    cfg = _rig(monkeypatch, tmp_path, _engine(url=None))
    cfg2 = _rig(monkeypatch, tmp_path, _engine("not-a-url-object"))
    assert cfg.get_main_option("sqlalchemy.url") == cfg2.get_main_option("sqlalchemy.url") == SETTINGS_URL
