"""Command line interface for Looop."""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TextIO

from . import __version__
from .core import (
    DEFAULT_LOG_DIR,
    IterationResult,
    LooopError,
    RunConfig,
    append_iteration_log_output,
    clean_logs,
    find_git_root,
    git_status_short,
    has_uncommitted_changes,
    init_loop,
    resolve_runtime_path,
    run_loop,
    status_report,
)


DESCRIPTION = (
    "Looop is a lightweight autonomous coding loop for Codex: it picks one task, "
    "implements it, updates progress, and repeats until done."
)


def build_parser(prog: str | None = None) -> argparse.ArgumentParser:
    """Build the top-level CLI parser."""

    display_name = prog or Path(sys.argv[0]).name or "looop"
    parser = argparse.ArgumentParser(
        prog=display_name,
        description=DESCRIPTION,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"looop {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="initialize .looop in this repository")
    init_parser.add_argument("--force", action="store_true", help="overwrite prompt and progress files")
    init_parser.set_defaults(func=cmd_init)

    run_parser = subparsers.add_parser("run", help="run the Codex loop")
    run_parser.add_argument("--max-iterations", type=int, default=20, help="maximum loop iterations")
    run_parser.add_argument("--codex-bin", default="codex", help="Codex CLI executable name or path")
    run_parser.add_argument("--codex-args", default="", help="extra arguments passed to `codex exec`")
    run_parser.add_argument(
        "--stop-on-no-changes",
        default=True,
        action=argparse.BooleanOptionalAction,
        help="stop when an iteration leaves no file changes",
    )
    run_parser.add_argument("--prompt-file", type=Path, default=Path(".looop/prompt.md"))
    run_parser.add_argument("--progress-file", type=Path, default=Path(".looop/progress.md"))
    run_parser.add_argument("--log-dir", type=Path, default=Path(".looop/logs"))
    run_parser.add_argument("--dry-run", action="store_true", help="show what would run without executing Codex")
    run_parser.add_argument(
        "--verbose",
        "--show-codex-output",
        dest="verbose",
        action="store_true",
        help="stream Codex stdout and stderr while it runs",
    )
    run_parser.set_defaults(func=cmd_run)

    status_parser = subparsers.add_parser("status", help="show Looop and repository status")
    status_parser.add_argument("--codex-bin", default="codex", help="Codex CLI executable name or path")
    status_parser.set_defaults(func=cmd_status)

    clean_parser = subparsers.add_parser("clean", help="delete .looop/logs")
    clean_parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    clean_parser.add_argument("--log-dir", type=Path, default=Path(".looop/logs"))
    clean_parser.set_defaults(func=cmd_clean)

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    paths = init_loop(force=args.force)
    if paths:
        print("Initialized Looop files:")
        for path in paths:
            print(f"- {path}")
    else:
        print("Looop is already initialized.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = RunConfig(
        max_iterations=args.max_iterations,
        codex_bin=args.codex_bin,
        codex_args=args.codex_args,
        stop_on_no_changes=args.stop_on_no_changes,
        prompt_file=args.prompt_file,
        progress_file=args.progress_file,
        log_dir=args.log_dir,
        dry_run=args.dry_run,
    )

    from .core import require_git_repo

    repo_root = require_git_repo()
    if has_uncommitted_changes(repo_root):
        print("Warning: the git working tree already has uncommitted changes.", file=sys.stderr)
        status = git_status_short(repo_root)
        if status:
            print(status, file=sys.stderr)

    reporter = TerminalRunReporter(max_iterations=config.max_iterations, verbose=args.verbose)
    results = run_loop(
        config,
        runner=reporter.run_command,
        on_iteration_started=reporter.iteration_started,
        on_iteration_completed=reporter.iteration_completed,
    )
    if not results:
        print("No iterations were run.")
        return 0

    last = results[-1]
    if last.codex_result.returncode != 0:
        return last.codex_result.returncode
    return 0


class TerminalRunReporter:
    """Terminal feedback for `looop run`."""

    _FRAMES = ("-", "\\", "|", "/")

    def __init__(
        self,
        *,
        max_iterations: int,
        verbose: bool,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        self.max_iterations = max_iterations
        self.verbose = verbose
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr
        self._lock = threading.Lock()
        self._log_lock = threading.Lock()
        self._current_log_file: Path | None = None
        self._spinner_visible = False
        self._spinner_width = 0

    def iteration_started(self, iteration: int, log_file: Path) -> None:
        self._current_log_file = log_file
        print(f"iteration {iteration}/{self.max_iterations}", file=self.stdout)
        print(f"  log: {_display_path(log_file)}", file=self.stdout)

    def iteration_completed(self, result: IterationResult) -> None:
        print(f"iteration {result.iteration} result", file=self.stdout)
        print(f"  changed files: {result.changed_files_count}", file=self.stdout)
        print(f"  done: {'yes' if result.done else 'no'}", file=self.stdout)
        print(f"  stop: {result.stop_reason or 'continue'}", file=self.stdout)
        print(f"  log: {_display_path(result.log_file)}", file=self.stdout)
        self._current_log_file = None

    def run_command(
        self,
        args: list[str] | str,
        *,
        cwd: Path,
        shell: bool = False,
        text: bool = True,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if not text or not capture_output:
            return subprocess.run(
                args,
                cwd=str(cwd),
                shell=shell,
                text=text,
                capture_output=capture_output,
            )

        process = subprocess.Popen(
            args,
            cwd=str(cwd),
            shell=shell,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        threads = [
            threading.Thread(
                target=self._drain_stream,
                args=(process.stdout, stdout_chunks, self.stdout, "stdout"),
                daemon=True,
            ),
            threading.Thread(
                target=self._drain_stream,
                args=(process.stderr, stderr_chunks, self.stderr, "stderr"),
                daemon=True,
            ),
        ]
        for thread in threads:
            thread.start()

        started = time.monotonic()
        frame = 0
        if self.stderr.isatty():
            while process.poll() is None:
                self._render_spinner(frame, time.monotonic() - started)
                frame += 1
                time.sleep(0.1)
            self._clear_spinner()
        else:
            print("  Codex running...", file=self.stderr)
            while process.poll() is None:
                time.sleep(0.2)

        returncode = process.wait()
        for thread in threads:
            thread.join()

        return subprocess.CompletedProcess(
            args=args,
            returncode=returncode,
            stdout="".join(stdout_chunks),
            stderr="".join(stderr_chunks),
        )

    def _drain_stream(
        self,
        stream: TextIO | None,
        chunks: list[str],
        target: TextIO,
        stream_name: str,
    ) -> None:
        if stream is None:
            return
        try:
            for line in iter(stream.readline, ""):
                chunks.append(line)
                self._append_log_output(stream_name, line)
                if self.verbose:
                    self._write_stream(target, line)
        finally:
            stream.close()

    def _append_log_output(self, stream_name: str, text: str) -> None:
        if self._current_log_file is None:
            return
        with self._log_lock:
            append_iteration_log_output(
                path=self._current_log_file,
                stream_name=stream_name,
                text=text,
            )

    def _render_spinner(self, frame: int, elapsed: float) -> None:
        line = f"  {self._FRAMES[frame % len(self._FRAMES)]} Codex running {_format_elapsed(elapsed)}"
        with self._lock:
            self.stderr.write("\r" + line)
            self.stderr.flush()
            self._spinner_visible = True
            self._spinner_width = len(line)

    def _clear_spinner(self) -> None:
        with self._lock:
            self._clear_spinner_locked()

    def _clear_spinner_locked(self) -> None:
        if not self._spinner_visible:
            return
        self.stderr.write("\r" + (" " * self._spinner_width) + "\r")
        self.stderr.flush()
        self._spinner_visible = False
        self._spinner_width = 0

    def _write_stream(self, target: TextIO, text: str) -> None:
        with self._lock:
            self._clear_spinner_locked()
            target.write(text)
            target.flush()


def _format_elapsed(seconds: float) -> str:
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def cmd_status(args: argparse.Namespace) -> int:
    print(status_report(codex_bin=args.codex_bin))
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    repo_root = find_git_root()
    log_dir = resolve_runtime_path(repo_root, args.log_dir, DEFAULT_LOG_DIR) if repo_root else args.log_dir
    removed = clean_logs(log_dir, yes=args.yes)
    if removed:
        print(f"Removed {log_dir}.")
    else:
        print(f"No logs removed from {log_dir}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point used by both `looop` and `lp`."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        print("\nExamples:")
        print("  looop init")
        print("  looop run --max-iterations 5")
        print("  lp status")
        return 0
    try:
        return int(args.func(args))
    except LooopError as exc:
        print(f"looop: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
