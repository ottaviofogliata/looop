from __future__ import annotations

import re
import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_both_console_script_aliases_are_configured(self) -> None:
        with (ROOT / "pyproject.toml").open("rb") as handle:
            data = tomllib.load(handle)

        scripts = data["project"]["scripts"]
        self.assertEqual(scripts["looop"], "looop.cli:main")
        self.assertEqual(scripts["lp"], "looop.cli:main")

    def test_makefile_has_required_targets(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        for target in ("install", "uninstall", "test", "lint", "clean"):
            self.assertRegex(makefile, rf"(?m)^{re.escape(target)}:")


if __name__ == "__main__":
    unittest.main()
