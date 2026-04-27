from __future__ import annotations

import unittest
import sys
import tempfile
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from looop.cli import TerminalRunReporter, build_parser


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

    def test_run_parser_accepts_verbose_output_aliases(self) -> None:
        parser = build_parser()

        verbose_args = parser.parse_args(["run", "--verbose"])
        alias_args = parser.parse_args(["run", "--show-codex-output"])

        self.assertTrue(verbose_args.verbose)
        self.assertTrue(alias_args.verbose)

    def test_terminal_reporter_streams_verbose_output_and_updates_log(self) -> None:
        stdout = StringIO()
        stderr = StringIO()
        reporter = TerminalRunReporter(max_iterations=1, verbose=True, stdout=stdout, stderr=stderr)

        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "iteration-1.log"
            log_file.write_text("== codex output (live) ==\n", encoding="utf-8")
            reporter.iteration_started(1, log_file)

            result = reporter.run_command(
                [
                    sys.executable,
                    "-c",
                    "import sys; print('stdout-line'); print('stderr-line', file=sys.stderr)",
                ],
                cwd=Path.cwd(),
            )

            log_text = log_file.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0)
        self.assertIn("stdout-line", result.stdout)
        self.assertIn("stderr-line", result.stderr)
        self.assertIn("stdout-line", stdout.getvalue())
        self.assertIn("stderr-line", stderr.getvalue())
        self.assertIn("[stdout] stdout-line", log_text)
        self.assertIn("[stderr] stderr-line", log_text)


if __name__ == "__main__":
    unittest.main()
