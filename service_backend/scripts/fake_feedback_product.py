"""A stand-in product for the feedback share-link phone step (lane
FEEDBACK-SUBSCRIBE), for local / test-copy hand tests ONLY.

It answers the two calls a product implements for SS
(``services/phone_verify.py``):

- ``POST /api/v1/external/ideation/contacts/lookup`` -> 200 with a name when the
  phone digits are in ``--known``, else 404;
- ``POST /api/v1/external/ideation/phone/send-code`` -> 202, and PRINTS the code
  it was asked to send (instead of WhatsApp), so the tester can type it.

Usage (no dependencies, stdlib only):

    python -m scripts.fake_feedback_product --port 8099 --known 60123450002="Contact B"

then point the tenant's consumer connection ``baseUrl`` at
``http://127.0.0.1:8099``. Never run this anywhere real: it accepts any API key.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict


def _handler(known: Dict[str, str]):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status: int, body: dict) -> None:
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            length = int(self.headers.get("content-length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._reply(400, {})
            digits = str(body.get("phoneDigits") or "")
            if self.path.endswith("/contacts/lookup"):
                name = known.get(digits)
                if name is None:
                    return self._reply(404, {})
                return self._reply(200, {"contactId": f"fake-{digits}", "name": name, "phone": body.get("phone")})
            if self.path.endswith("/phone/send-code"):
                print(f"CODE for +{digits}: {body.get('code')}", flush=True)
                return self._reply(202, {})
            return self._reply(404, {})

        def log_message(self, *args) -> None:  # quiet: only the CODE lines print
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument(
        "--known",
        action="append",
        default=[],
        help='digits="Name" of a phone the product knows (repeatable), e.g. 60123450002="Contact B"',
    )
    args = parser.parse_args()
    known: Dict[str, str] = {}
    for item in args.known:
        digits, _, name = item.partition("=")
        known[digits.strip().lstrip("+")] = name.strip().strip('"') or "Contact"
    print(f"fake product on 127.0.0.1:{args.port}, knows {sorted(known)}", flush=True)
    HTTPServer(("127.0.0.1", args.port), _handler(known)).serve_forever()


if __name__ == "__main__":
    main()
