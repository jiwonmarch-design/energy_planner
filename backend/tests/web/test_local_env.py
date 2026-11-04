from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.web.local_env import load_env_file


class LocalEnvTests(unittest.TestCase):
    def test_loads_values_and_ignores_comments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "# local only\nOPENAI_API_KEY='test-key'\nOPENAI_MODEL=gpt-4o-mini\n",
                encoding="utf-8",
            )
            environ: dict[str, str] = {}

            loaded = load_env_file(path, environ=environ)

            self.assertEqual(loaded, {"OPENAI_API_KEY", "OPENAI_MODEL"})
            self.assertEqual(environ["OPENAI_API_KEY"], "test-key")
            self.assertEqual(environ["OPENAI_MODEL"], "gpt-4o-mini")

    def test_existing_environment_has_priority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("OPENAI_API_KEY=file-key\n", encoding="utf-8")
            environ = {"OPENAI_API_KEY": "process-key"}

            loaded = load_env_file(path, environ=environ)

            self.assertEqual(loaded, set())
            self.assertEqual(environ["OPENAI_API_KEY"], "process-key")

    def test_invalid_line_reports_location_without_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("OPENAI_API_KEY test-secret\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, r"\.env:1: KEY=VALUE") as caught:
                load_env_file(path, environ={})

            self.assertNotIn("test-secret", str(caught.exception))

    def test_missing_file_is_optional(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"

            self.assertEqual(load_env_file(path, environ={}), set())


if __name__ == "__main__":
    unittest.main()
