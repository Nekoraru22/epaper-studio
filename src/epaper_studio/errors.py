"""Errors that carry a stable, translatable code.

The backend never sends user-facing sentences. It sends a ``code`` plus the
``params`` needed to build the sentence, and the web UI translates it into the
reader's language. ``message`` is an English fallback for logs and API clients.
"""

from __future__ import annotations

from typing import Any


class StudioError(Exception):
    """Base error for anything the user may need to read."""

    status: int = 400

    def __init__(self, code: str, message: str = "", *, status: int | None = None, **params: Any):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.params = params
        if status is not None:
            self.status = status

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "params": self.params}
