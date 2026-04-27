from __future__ import annotations

import unittest
from contextlib import redirect_stderr
from io import StringIO

from looop.cli import build_parser


class CliTests(unittest.TestCase):
    def test_parser_can_use_lp_program_name(self) -> None:
        parser = build_parser(prog="lp")

        self.assertEqual(parser.prog, "lp")

    def test_run_parser_has_no_test_or_commit_options(self) -> None:
        parser = build_parser()

        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["run", "--test-command", "pytest -q"])

            with self.assertRaises(SystemExit):
                parser.parse_args(["run", "--auto-commit"])


if __name__ == "__main__":
    unittest.main()
