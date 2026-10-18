"""Railway/Railpack entrypoint.

Railpack only auto-starts FastAPI when main.py is in the project root.
The application itself lives in app.main.
"""

from app.main import app

__all__ = ["app"]
