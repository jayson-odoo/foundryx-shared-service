"""AC-08-38 independent proof: 500-on-page-3 stub via the get_http_transport
FastAPI dependency seam, against the /autocount/http/preview route only
(the seam this dependency actually covers). Run with the backend .venv
python, from service_backend/, against an isolated TestClient instance
(NOT the live :8007 process) - never a Sorento push.
"""
import httpx
from fastapi.testclient import TestClient

from app.main import app
from modules.autocount.http_client import get_http_transport


def handler(request: httpx.Request) -> httpx.Response:
    page = int(request.url.params.get("page", "1"))
    if page == 3:
        return httpx.Response(500, text="boom")
    return httpx.Response(
        200,
        json={
            "TotalCount": 5, "Page": page, "PageSize": 1, "TotalPages": 5,
            "Data": [{"ItemCode": f"A{page}", "LastModified": "2026-08-01T09:00:00"}],
        },
    )


stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
app.dependency_overrides[get_http_transport] = lambda: stub_transport

client = TestClient(app)

login = client.post("/auth/login", json={"email": "demo@example.com", "password": "demo1234"})
print("LOGIN", login.status_code)
token = login.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# A real open connection + real page-walk against the stub. Use the
# lane's existing "Mocha REST" no-auth connection id.
conn_id = "3c9c43b8-08ec-4bc4-a87b-2805a77adf6f"
print("CONN_ID", conn_id)

resp = client.post(
    "/autocount/http/preview",
    headers=headers,
    json={"connectionId": conn_id, "path": "/itembypage"},
)
print("STATUS", resp.status_code)
print("BODY", resp.text[:500])
# FINDING (not the originally-expected 422): this route caps to PAGE 1 ONLY
# (AC-08-14, the Source tab's "Test" button sample), so a page-3 failure in
# the stub is never reached - status 200, page-1 data only. The real
# multi-page walk that CAN fail on page 3 lives in `preview_task`/
# `run_autocount_sync`, which build their OWN `HttpApiClient` (not through
# this `get_http_transport` seam) - see the pytest citations in the README
# for the actual AC-08-38 proof.
assert resp.status_code == 200, f"expected 200 (page-1-only route), got {resp.status_code}: {resp.text}"
body = resp.json()
assert body["envelope"] == "paged" and len(body["rows"]) == 1
print(
    "FINDING: /autocount/http/preview caps to page 1 (AC-08-14 Test-button "
    "sample) - a page-3 stub failure never reaches this route. The full "
    "page-walk failure (AC-08-38) is proven via preview_task/"
    "run_autocount_sync instead - see the pytest citations in the README."
)
