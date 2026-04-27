"""Core orchestration primitives for the Looop CLI."""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .prompts import DEFAULT_PROGRESS, DEFAULT_PROMPT, DONE_MARKER

DEFAULT_PROMPT_PATH = Path(".looop/prompt.md")
DEFAULT_PROGRESS_PATH = Path(".looop/progress.md")
DEFAULT_LOG_DIR = Path(".looop/logs")
DEFAULT_CODEX_MODEL = "gpt-5.5"
DEFAULT_REASONING_EFFORT = "xhigh"


class LooopError(RuntimeError):
    """Raised for user-facing operational errors."""


@dataclass(frozen=True)
class CommandResult:
    """Captured subprocess result."""

    args: Sequence[str] | str
    returncode: int
    stdout: str
    stderr: str

    @property
    def display(self) -> str:
        if isinstance(self.args, str):
            return self.args
        return shlex.join(str(part) for part in self.args)


@dataclass(frozen=True)
class WorktreeSnapshot:
    """A lightweight content and git-status snapshot of the current worktree."""

    status: tuple[str, ...]
    files: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class RunConfig:
    """Runtime configuration for the Codex loop."""

    max_iterations: int = 20
    codex_bin: str = "codex"
    codex_args: str = ""
    stop_on_no_changes: bool = True
    prompt_file: Path = DEFAULT_PROMPT_PATH
    progress_file: Path = DEFAULT_PROGRESS_PATH
    log_dir: Path = DEFAULT_LOG_DIR
    dry_run: bool = False


@dataclass(frozen=True)
class IterationResult:
    """Outcome of one loop iteration."""

    iteration: int
    codex_result: CommandResult
    changed: bool
    done: bool
    stop_reason: str | None
    log_file: Path


Runner = Callable[..., subprocess.CompletedProcess[str]]


def run_command(
    args: Sequence[str] | str,
    *,
    cwd: Path,
    shell: bool = False,
    runner: Runner = subprocess.run,
) -> CommandResult:
    """Run a command and capture text output."""

    completed = runner(
        args,
        cwd=str(cwd),
        shell=shell,
        text=True,
        capture_output=True,
    )
    return CommandResult(
        args=args,
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def find_git_root(cwd: Path | None = None) -> Path | None:
    """Return the git root for cwd, or None when cwd is not inside a repo."""

    base = (cwd or Path.cwd()).resolve()
    result = run_command(["git", "rev-parse", "--show-toplevel"], cwd=base)
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return Path(root).resolve() if root else None


def require_git_repo(cwd: Path | None = None) -> Path:
    """Return the current git root or raise a user-facing error."""

    root = find_git_root(cwd)
    if root is None:
        raise LooopError("This command must be run inside a git repository.")
    return root


def codex_available(codex_bin: str = "codex") -> bool:
    """Return whether the configured Codex executable is available."""

    return shutil.which(codex_bin) is not None


def require_codex(codex_bin: str = "codex") -> None:
    """Raise a user-facing error when Codex CLI is not available."""

    if not codex_available(codex_bin):
        raise LooopError(
            f"Codex CLI binary not found: {codex_bin!r}. Install Codex CLI or pass --codex-bin."
        )


def has_done_marker(progress_file: Path) -> bool:
    """Return whether the progress file contains the Looop done marker."""

    try:
        return DONE_MARKER in progress_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False


def ensure_loop_files(
    *,
    prompt_file: Path,
    progress_file: Path,
    log_dir: Path,
    loop_dir: Path | None = None,
    force: bool = False,
) -> list[Path]:
    """Create the Looop runtime files that do not already exist."""

    created_or_updated: list[Path] = []
    resolved_loop_dir = loop_dir or _infer_loop_dir(prompt_file, progress_file, log_dir)
    if not resolved_loop_dir.exists():
        resolved_loop_dir.mkdir(parents=True)
        created_or_updated.append(resolved_loop_dir)

    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    if force or not prompt_file.exists():
        prompt_file.write_text(DEFAULT_PROMPT, encoding="utf-8")
        created_or_updated.append(prompt_file)

    if force or not progress_file.exists():
        progress_file.write_text(DEFAULT_PROGRESS, encoding="utf-8")
        created_or_updated.append(progress_file)

    gitignore = log_dir / ".gitignore"
    if force or not gitignore.exists():
        gitignore.write_text("*\n!.gitignore\n", encoding="utf-8")
        created_or_updated.append(gitignore)

    return created_or_updated


def _infer_loop_dir(prompt_file: Path, progress_file: Path, log_dir: Path) -> Path:
    for candidate in (prompt_file.parent, progress_file.parent, log_dir.parent):
        if candidate.name == ".looop":
            return candidate
    return Path(".looop")


def init_loop(force: bool = False) -> list[Path]:
    """Initialize .looop in the current git repository."""

    repo_root = require_git_repo()
    return ensure_loop_files(
        prompt_file=repo_root / DEFAULT_PROMPT_PATH,
        progress_file=repo_root / DEFAULT_PROGRESS_PATH,
        log_dir=repo_root / DEFAULT_LOG_DIR,
        loop_dir=repo_root / ".looop",
        force=force,
    )


def build_codex_command(codex_bin: str, codex_args: str, prompt: str) -> list[str]:
    """Build the Codex exec command without invoking a shell."""

    try:
        extra_args = shlex.split(codex_args)
    except ValueError as exc:
        raise LooopError(f"Could not parse --codex-args: {exc}") from exc

    default_args: list[str] = []
    if not _has_model_arg(extra_args):
        default_args.extend(["--model", DEFAULT_CODEX_MODEL])
    if not _has_config_arg(extra_args, "model_reasoning_effort"):
        default_args.extend(["--config", f"model_reasoning_effort={DEFAULT_REASONING_EFFORT}"])

    return [codex_bin, "exec", *default_args, *extra_args, prompt]


def _has_model_arg(args: Sequence[str]) -> bool:
    return any(arg == "-m" or arg == "--model" or arg.startswith("--model=") for arg in args)


def _has_config_arg(args: Sequence[str], key: str) -> bool:
    for index, arg in enumerate(args):
        if arg in {"-c", "--config"} and index + 1 < len(args):
            if args[index + 1].split("=", 1)[0] == key:
                return True
        if arg.startswith("--config="):
            if arg.removeprefix("--config=").split("=", 1)[0] == key:
                return True
    return False


def git_status_short(repo_root: Path) -> str:
    """Return `git status --short` output for display."""

    result = run_command(["git", "status", "--short"], cwd=repo_root)
    return result.stdout.strip()


def has_uncommitted_changes(repo_root: Path) -> bool:
    """Return whether git reports any working tree changes."""

    return bool(git_status_short(repo_root))


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _is_excluded(path: Path, excluded_roots: Iterable[Path]) -> bool:
    return any(_is_relative_to(path, root) for root in excluded_roots)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.lstat()
    return f"{stat.st_mode}:{stat.st_size}:{digest.hexdigest()}"


def _status_lines(repo_root: Path, excluded_roots: Iterable[Path]) -> tuple[str, ...]:
    result = run_command(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo_root,
    )
    lines: list[str] = []
    for line in result.stdout.splitlines():
        path_text = line[3:] if len(line) > 3 else ""
        if path_text.startswith('"') and path_text.endswith('"'):
            lines.append(line)
            continue
        if path_text and _is_excluded(repo_root / path_text, excluded_roots):
            continue
        lines.append(line)
    return tuple(sorted(lines))


def take_worktree_snapshot(repo_root: Path, *, exclude_roots: Iterable[Path] = ()) -> WorktreeSnapshot:
    """Capture tracked and untracked content, excluding ignored files and logs."""

    excluded = tuple(path.resolve() for path in exclude_roots)
    result = run_command(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=repo_root,
    )
    files: list[tuple[str, str]] = []
    for raw_path in result.stdout.split("\0"):
        if not raw_path:
            continue
        path = repo_root / raw_path
        if _is_excluded(path, excluded):
            continue
        if not path.exists():
            files.append((raw_path, "<deleted>"))
        elif path.is_symlink():
            files.append((raw_path, f"symlink:{os.readlink(path)}"))
        elif path.is_file():
            files.append((raw_path, _hash_file(path)))
    return WorktreeSnapshot(
        status=_status_lines(repo_root, excluded),
        files=tuple(sorted(files)),
    )


def worktree_changed(before: WorktreeSnapshot, after: WorktreeSnapshot) -> bool:
    """Return whether two worktree snapshots differ."""

    return before != after


def next_iteration_number(log_dir: Path) -> int:
    """Return the next available iteration number for log naming."""

    highest = 0
    if log_dir.exists():
        for path in log_dir.glob("iteration-*.log"):
            stem = path.stem.removeprefix("iteration-")
            if stem.isdigit():
                highest = max(highest, int(stem))
    return highest + 1


def latest_log_file(log_dir: Path) -> Path | None:
    """Return the newest iteration log, if any."""

    logs = [path for path in log_dir.glob("iteration-*.log") if path.is_file()]
    if not logs:
        return None
    return max(logs, key=lambda path: (path.stat().st_mtime, path.name))


def resolve_runtime_path(repo_root: Path, path: Path, default_path: Path) -> Path:
    """Resolve default runtime paths at the git root and custom paths at cwd."""

    if path.is_absolute():
        return path
    if path == default_path:
        return repo_root / path
    return path.resolve()


def write_iteration_log(
    *,
    path: Path,
    iteration: int,
    codex_command: Sequence[str],
    codex_result: CommandResult | None,
    final_result: str,
) -> None:
    """Write a complete iteration log."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"timestamp: {datetime.now(timezone.utc).isoformat()}",
        f"iteration: {iteration}",
        f"codex_command: {shlex.join(str(part) for part in codex_command)}",
        "",
        "== codex stdout ==",
        codex_result.stdout if codex_result else "",
        "",
        "== codex stderr ==",
        codex_result.stderr if codex_result else "",
    ]
    lines.extend(["", "== final result ==", final_result, ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def run_loop(config: RunConfig, *, runner: Runner = subprocess.run) -> list[IterationResult]:
    """Run Codex repeatedly until a configured stop condition is reached."""

    repo_root = require_git_repo()
    require_codex(config.codex_bin)

    if config.max_iterations < 1:
        raise LooopError("--max-iterations must be at least 1.")

    prompt_file = resolve_runtime_path(repo_root, config.prompt_file, DEFAULT_PROMPT_PATH)
    progress_file = resolve_runtime_path(repo_root, config.progress_file, DEFAULT_PROGRESS_PATH)
    log_dir = resolve_runtime_path(repo_root, config.log_dir, DEFAULT_LOG_DIR)

    ensure_loop_files(
        prompt_file=prompt_file,
        progress_file=progress_file,
        log_dir=log_dir,
        loop_dir=repo_root / ".looop",
    )

    if has_done_marker(progress_file):
        return []

    prompt = prompt_file.read_text(encoding="utf-8")
    command = build_codex_command(config.codex_bin, config.codex_args, prompt)
    if config.dry_run:
        iteration = next_iteration_number(log_dir)
        log_file = log_dir / f"iteration-{iteration}.log"
        write_iteration_log(
            path=log_file,
            iteration=iteration,
            codex_command=command,
            codex_result=None,
            final_result="dry-run: Codex was not executed",
        )
        dry_result = CommandResult(command, 0, "", "")
        return [
            IterationResult(
                iteration=iteration,
                codex_result=dry_result,
                changed=False,
                done=has_done_marker(progress_file),
                stop_reason="dry-run",
                log_file=log_file,
            )
        ]

    results: list[IterationResult] = []
    iteration = next_iteration_number(log_dir)
    for index in range(config.max_iterations):
        prompt = prompt_file.read_text(encoding="utf-8")
        command = build_codex_command(config.codex_bin, config.codex_args, prompt)
        log_file = log_dir / f"iteration-{iteration}.log"
        before = take_worktree_snapshot(repo_root, exclude_roots=(log_dir,))
        codex_result = run_command(command, cwd=repo_root, runner=runner)

        stop_reason: str | None = None
        changed = False

        if codex_result.returncode != 0:
            stop_reason = f"codex exited with status {codex_result.returncode}"
        else:
            after = take_worktree_snapshot(repo_root, exclude_roots=(log_dir,))
            changed = worktree_changed(before, after)

            if stop_reason is None and config.stop_on_no_changes and not changed:
                stop_reason = "no files changed"

            if stop_reason is None and has_done_marker(progress_file):
                stop_reason = DONE_MARKER

            if stop_reason is None and index == config.max_iterations - 1:
                stop_reason = "max iterations reached"

        done = has_done_marker(progress_file)
        final_result = (
            f"changed={changed}\n"
            f"done={done}\n"
            f"stop_reason={stop_reason or 'continue'}"
        )
        write_iteration_log(
            path=log_file,
            iteration=iteration,
            codex_command=command,
            codex_result=codex_result,
            final_result=final_result,
        )

        result = IterationResult(
            iteration=iteration,
            codex_result=codex_result,
            changed=changed,
            done=done,
            stop_reason=stop_reason,
            log_file=log_file,
        )
        results.append(result)

        if stop_reason is not None:
            break
        iteration += 1

    return results


def progress_summary(progress_file: Path, *, max_lines: int = 10) -> str:
    """Return a short display summary of the progress file."""

    if not progress_file.exists():
        return "missing"
    lines = [line.strip() for line in progress_file.read_text(encoding="utf-8").splitlines()]
    meaningful = [line for line in lines if line]
    if not meaningful:
        return "empty"
    return "\n".join(meaningful[:max_lines])


def status_report(codex_bin: str = "codex") -> str:
    """Build a human-readable status report for the current directory."""

    cwd = Path.cwd()
    repo_root = find_git_root(cwd)
    base = repo_root or cwd
    loop_dir = base / ".looop"
    progress_file = base / DEFAULT_PROGRESS_PATH
    log_dir = base / DEFAULT_LOG_DIR
    latest_log = latest_log_file(log_dir) if log_dir.exists() else None
    status = git_status_short(repo_root) if repo_root else ""

    lines = [
        "Looop status",
        f"- .looop exists: {'yes' if loop_dir.exists() else 'no'}",
        f"- git repository: {'yes' if repo_root else 'no'}",
    ]
    if repo_root:
        lines.append(f"- git root: {repo_root}")
    lines.extend(
        [
            f"- Codex CLI available: {'yes' if codex_available(codex_bin) else 'no'}",
            f"- done marker present: {'yes' if has_done_marker(progress_file) else 'no'}",
            "- progress summary:",
            progress_summary(progress_file),
            f"- latest log: {latest_log if latest_log else 'none'}",
            "- git working tree:",
            status if status else "clean",
        ]
    )
    return "\n".join(lines)


def clean_logs(log_dir: Path = Path(".looop/logs"), *, yes: bool = False) -> bool:
    """Delete the Looop log directory, asking for confirmation unless yes is set."""

    if not log_dir.exists():
        return False
    if not yes:
        answer = input(f"Delete {log_dir}? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            return False
    shutil.rmtree(log_dir)
    return True
