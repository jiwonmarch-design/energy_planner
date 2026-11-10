import os
import unittest
from email.message import Message
from http import HTTPStatus
from unittest.mock import Mock, patch

from backend.app.web.cors import CorsHandlerMixin, cors_origin


FRONTEND_ORIGIN = "https://energy-planner-mini.axworks.site"


class StubHandler:
    def __init__(self, path: str, origin: str) -> None:
        self.path = path
        self.headers = Message()
        if origin:
            self.headers["Origin"] = origin
        self.send_header = Mock()
        self.send_response = Mock()
        self.send_error = Mock()
        self.base_end_headers_called = False

    def end_headers(self) -> None:
        self.base_end_headers_called = True


class TestHandler(CorsHandlerMixin, StubHandler):
    pass


def make_handler(path: str = "/api/health", origin: str = FRONTEND_ORIGIN) -> TestHandler:
    return TestHandler(path, origin)


class CorsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {"CORS_ALLOWED_ORIGINS": FRONTEND_ORIGIN},
            clear=False,
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()

    def test_exact_configured_origin_is_allowed(self) -> None:
        handler = make_handler()
        self.assertEqual(cors_origin(handler), FRONTEND_ORIGIN)

    def test_unconfigured_origin_is_rejected(self) -> None:
        handler = make_handler(origin="https://example.com")
        self.assertIsNone(cors_origin(handler))

    def test_api_response_adds_cors_headers(self) -> None:
        handler = make_handler()
        handler.end_headers()
        handler.send_header.assert_any_call("Access-Control-Allow-Origin", FRONTEND_ORIGIN)
        handler.send_header.assert_any_call("Vary", "Origin")
        self.assertTrue(handler.base_end_headers_called)

    def test_preflight_allows_configured_frontend(self) -> None:
        handler = make_handler(path="/api/quality")
        handler.do_OPTIONS()
        handler.send_response.assert_called_once_with(HTTPStatus.NO_CONTENT)
        handler.send_header.assert_any_call("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        handler.send_header.assert_any_call("Access-Control-Allow-Headers", "Content-Type")
        self.assertTrue(handler.base_end_headers_called)

    def test_preflight_rejects_unconfigured_origin(self) -> None:
        handler = make_handler(path="/api/quality", origin="https://example.com")
        handler.do_OPTIONS()
        handler.send_error.assert_called_once_with(HTTPStatus.FORBIDDEN)


if __name__ == "__main__":
    unittest.main()
