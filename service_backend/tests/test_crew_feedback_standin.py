"""FEEDBACK-SUBSCRIBE crew pass 4025e5e9: a documented helper points a test
copy's product phone step at the local stand-in product, refusing anything
that could be production, and puts the real connection back afterwards."""
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.ideation.services.phone_verify import product_target
from scripts.crew_feedback_standin import StandinRefused, check_safe, restore, seed
from tests.test_ideation_follow_share import PRODUCT_BASE, _product_connection  # noqa: F401
from tests.test_ideation_public_status import _auth, ideation_client, setup  # noqa: F401

LOCAL = "postgresql://u:p@localhost:5432/copy"


@pytest.mark.parametrize(
    "env,url,allow",
    [
        ("production", LOCAL, True),
        ("staging", LOCAL, False),
        ("development", "postgresql://u:p@db.internal:5432/x", True),
        ("development", "postgresql://u:p@10.0.0.5/x", False),
    ],
)
def test_standin_refuses_anything_but_a_local_non_prod_copy(env, url, allow):
    with pytest.raises(StandinRefused):
        check_safe(env, url, allow_non_dev=allow)


def test_standin_allows_a_local_copy():
    check_safe("development", LOCAL, allow_non_dev=False)
    check_safe("staging", "postgresql://u:p@127.0.0.1/x", allow_non_dev=True)


def test_standin_seed_and_restore_swap_the_consumer_connection(setup):
    s = setup
    _product_connection(s)
    db = s["factory"]()
    try:
        assert product_target(db, DEFAULT_TENANT_ID, s["product_id"])[0] == PRODUCT_BASE
        out = seed(db, "default", "http://127.0.0.1:8099/")
        assert out["parked"] == 1
        assert product_target(db, DEFAULT_TENANT_ID, s["product_id"])[0] == "http://127.0.0.1:8099"
        # Idempotent: a second seed re-points, parks nothing new, one stand-in row.
        assert seed(db, "default", "http://127.0.0.1:8100")["parked"] == 1
        assert db.query(Connection).filter(Connection.provider == "zzt-standin").count() == 1
        assert restore(db, "default")["restored"] == 1
        assert product_target(db, DEFAULT_TENANT_ID, s["product_id"])[0] == PRODUCT_BASE
        assert db.query(Connection).filter(Connection.provider == "zzt-standin").count() == 0
        assert restore(db, "default")["restored"] == 0
    finally:
        db.close()


def test_standin_unknown_tenant_is_refused(setup):
    db = setup["factory"]()
    try:
        with pytest.raises(StandinRefused):
            seed(db, "no-such-tenant", "http://127.0.0.1:8099")
    finally:
        db.close()
