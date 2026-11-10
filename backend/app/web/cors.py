"""CORS policy for browser access to the Energy Planner API."""

from __future__ import annotations

import os
from http import HTTPStatus
from urllib.parse import urlparse


def cors_origin(handler) -> str | None:
    """Return the request origin only when it is explicitly allowed."""

    origin = handler.headers.get("Origin", "")
    allowed = {
        item.strip()
        for item in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
        if item.strip()
    }
    return origin if origin in allowed else None


class CorsHandlerMixin:
    """Add an exact-origin CORS policy to /api/* request handlers."""

    def end_headers(self) -> None:
        path = urlparse(self.path).path
        origin = cors_origin(self)
        if path.startswith("/api/") and origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        super().end_headers()

    def do_OPTIONS(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not path.startswith("/api/") or not cors_origin(self):
            self.send_error(HTTPStatus.FORBIDDEN)
            return

        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()
