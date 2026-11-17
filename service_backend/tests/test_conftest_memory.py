"""CI hang on PR #253 (crew pass da65343f): every xdist worker grew to ~4.5 GB
and the kernel OOM-killed one, after which xdist waited forever and the job hit
its 30 min timeout.

Cause: FastAPI classifies each dependency callable through three
``functools.lru_cache(maxsize=4096)`` caches keyed by the callable itself.
Every test installs a fresh ``get_db`` override closure, which captures that
test's ``sessionmaker`` -> engine -> whole in-memory database copy, so a worker
kept the last ~4096 tests' databases alive. ``_clear_fastapi_callable_caches``
(run after every test by conftest) lets them be freed.
"""
import gc
import weakref

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _classify_like_fastapi(call) -> None:
    from fastapi.dependencies import models

    for name in ("_is_gen_callable", "_is_async_gen_callable", "_is_coroutine_callable"):
        fn = getattr(models, name, None)
        if fn is not None:
            fn(call)


def test_an_override_closure_does_not_keep_its_test_database_alive():
    from tests.conftest import _clear_fastapi_callable_caches as release_fastapi_call_caches

    engine = create_engine("sqlite://", poolclass=StaticPool)
    factory = sessionmaker(bind=engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    _classify_like_fastapi(override_get_db)
    ref = weakref.ref(engine)
    engine.dispose()
    del engine, factory, override_get_db
    release_fastapi_call_caches()
    gc.collect()
    assert ref() is None
