import os
import sys

# Allow ``python -m code_runner`` from the service_backend dir AND
# ``python code_runner`` style launches from the runner image.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from code_runner.server import serve  # noqa: E402

if __name__ == "__main__":
    serve(
        host=os.environ.get("CODE_RUNNER_HOST", "0.0.0.0"),
        port=int(os.environ.get("CODE_RUNNER_PORT") or 8011),
    )
