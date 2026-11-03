from __future__ import annotations

import unittest

from backend.app.web.server import FRONTEND_ROOT, resolve_frontend_target


class FrontendRouteCases(unittest.TestCase):
    def test_history_api_routes_resolve_to_index(self) -> None:
        expected = (FRONTEND_ROOT / "index.html").resolve()
        for path in ("/", "/workspace", "/dashboard"):
            with self.subTest(path=path):
                self.assertEqual(resolve_frontend_target(path), expected)

    def test_static_assets_still_resolve(self) -> None:
        self.assertEqual(
            resolve_frontend_target("/app.js"),
            (FRONTEND_ROOT / "app.js").resolve(),
        )

    def test_unknown_and_traversal_paths_are_rejected(self) -> None:
        self.assertIsNone(resolve_frontend_target("/unknown"))
        self.assertIsNone(resolve_frontend_target("/../docs/mvp.md"))


if __name__ == "__main__":
    unittest.main()
