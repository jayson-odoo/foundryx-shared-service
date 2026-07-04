"""Entry point. `python main.py` (reads .env) or `uvicorn main:app --reload`."""
from app.main import app

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    from app.config import settings

    uvicorn.run("main:app", host=settings.api_host, port=settings.api_port, reload=True)
