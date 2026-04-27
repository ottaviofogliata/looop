"""Command line interface for Looop."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core import (
    DEFAULT_LOG_DIR,
    LooopError,
    RunConfig,
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

    results = run_loop(config)
    if not results:
        print("No iterations were run.")
        return 0

    for result in results:
        print(
            "iteration "
            f"{result.iteration}: changed={result.changed} "
            f"done={result.done} log={result.log_file}"
        )
        if result.stop_reason:
            print(f"stopped: {result.stop_reason}")

    last = results[-1]
    if last.codex_result.returncode != 0:
        return last.codex_result.returncode
    return 0


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
