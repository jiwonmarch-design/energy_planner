"""Load local development variables without adding a dotenv dependency."""

from __future__ import annotations

import os
import re
from collections.abc import MutableMapping
from pathlib import Path


ENV_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def load_env_file(
    path: Path,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> set[str]:
    """Load KEY=VALUE lines while preserving variables already in the environment."""

    if not path.is_file():
        return set()

    target = os.environ if environ is None else environ
    loaded: set[str] = set()
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()

        name, separator, raw_value = line.partition("=")
        name = name.strip()
        if not separator or not ENV_NAME_PATTERN.fullmatch(name):
            raise ValueError(f"{path.name}:{line_number}: KEY=VALUE format expected")

        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if name not in target:
            target[name] = value
            loaded.add(name)
    return loaded
