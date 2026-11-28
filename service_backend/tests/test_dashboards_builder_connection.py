"""Builder connection rules: an Anthropic connection is required once ANY LLM connection exists; only a
tenant with none at all, in development, uses the stub."""
from app.ai.stub import stub_fixtures
from tests.dashboards_helpers import dash, llm  # noqa: F401 - pytest fixtures
from tests.dashboards_helpers import OWNER, assert_flat_error, ops_out, turn
from tests.test_dashboards_v2 import _llm_conn


def test_non_anthropic_connection_is_409_even_in_development(client, dash, llm):
    db = dash.sf()
    try:
        _llm_conn(db, "gemini")
    finally:
        db.close()
    body = assert_flat_error(turn(client, dash.sorento, OWNER, "x"), 409, "ai_not_configured")
    assert "Anthropic" in body["message"] and llm.n == 0


def test_no_connection_at_all_uses_the_stub_in_development(client, dash):
    with stub_fixtures(ops_out("ok")):
        assert turn(client, dash.sorento, OWNER, "x").status_code == 200
