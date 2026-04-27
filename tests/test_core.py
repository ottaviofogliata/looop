from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from looop import core
from looop.prompts import DONE_MARKER


@contextmanager
def temp_cwd():
    previous = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        os.chdir(path)
        try:
            yield path
        finally:
            os.chdir(previous)


def git_init(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)


class CoreTests(unittest.TestCase):
    def test_init_creates_expected_files(self) -> None:
        with temp_cwd() as repo:
            git_init(repo)

            created = core.init_loop()

            self.assertTrue((repo / ".looop/prompt.md").is_file())
            self.assertTrue((repo / ".looop/progress.md").is_file())
            self.assertTrue((repo / ".looop/logs").is_dir())
            self.assertIn((repo / ".looop/prompt.md").resolve(), [path.resolve() for path in created])

    def test_init_from_subdirectory_uses_repo_root(self) -> None:
        with temp_cwd() as repo:
            git_init(repo)
            nested = repo / "src/package"
            nested.mkdir(parents=True)
            os.chdir(nested)

            core.init_loop()

            self.assertTrue((repo / ".looop/prompt.md").is_file())
            self.assertFalse((nested / ".looop").exists())

    def test_init_does_not_overwrite_prompt_unless_forced(self) -> None:
        with temp_cwd() as repo:
            git_init(repo)
            core.init_loop()
            prompt = repo / ".looop/prompt.md"
            prompt.write_text("custom prompt", encoding="utf-8")

            core.init_loop()
            self.assertEqual(prompt.read_text(encoding="utf-8"), "custom prompt")

            core.init_loop(force=True)
            self.assertNotEqual(prompt.read_text(encoding="utf-8"), "custom prompt")

    def test_done_marker_detection(self) -> None:
        with temp_cwd() as repo:
            progress = repo / "progress.md"
            progress.write_text("not done", encoding="utf-8")
            self.assertFalse(core.has_done_marker(progress))

            progress.write_text(f"all done\n{DONE_MARKER}\n", encoding="utf-8")
            self.assertTrue(core.has_done_marker(progress))

    def test_no_change_detection_ignores_logs(self) -> None:
        with temp_cwd() as repo:
            git_init(repo)
            core.ensure_loop_files(
                prompt_file=Path(".looop/prompt.md"),
                progress_file=Path(".looop/progress.md"),
                log_dir=Path(".looop/logs"),
            )

            before = core.take_worktree_snapshot(repo, exclude_roots=(repo / ".looop/logs",))
            (repo / ".looop/logs/iteration-1.log").write_text("log", encoding="utf-8")
            after_log = core.take_worktree_snapshot(repo, exclude_roots=(repo / ".looop/logs",))
            self.assertFalse(core.worktree_changed(before, after_log))

            (repo / "example.txt").write_text("changed", encoding="utf-8")
            after_file = core.take_worktree_snapshot(repo, exclude_roots=(repo / ".looop/logs",))
            self.assertTrue(core.worktree_changed(before, after_file))

    def test_command_construction_for_codex(self) -> None:
        command = core.build_codex_command("codex", "", "do one thing")
        self.assertEqual(
            command,
            [
                "codex",
                "exec",
                "--model",
                "gpt-5.5",
                "--config",
                "model_reasoning_effort=xhigh",
                "do one thing",
            ],
        )

    def test_command_construction_allows_codex_arg_overrides(self) -> None:
        command = core.build_codex_command(
            "codex",
            "--model gpt-5.1-codex-max --config model_reasoning_effort=low --config service_tier=fast",
            "do one thing",
        )
        self.assertEqual(
            command,
            [
                "codex",
                "exec",
                "--model",
                "gpt-5.1-codex-max",
                "--config",
                "model_reasoning_effort=low",
                "--config",
                "service_tier=fast",
                "do one thing",
            ],
        )

    def test_status_report_basic_behavior(self) -> None:
        with temp_cwd() as repo:
            git_init(repo)
            core.init_loop()

            report = core.status_report()

            self.assertIn(".looop exists: yes", report)
            self.assertIn("git repository: yes", report)
            self.assertIn("done marker present: no", report)
            self.assertIn("git working tree:", report)

    def test_clean_removes_logs(self) -> None:
        with temp_cwd() as repo:
            log_dir = repo / ".looop/logs"
            log_dir.mkdir(parents=True)
            (log_dir / "iteration-1.log").write_text("log", encoding="utf-8")

            removed = core.clean_logs(Path(".looop/logs"), yes=True)

            self.assertTrue(removed)
            self.assertFalse(log_dir.exists())

    def test_run_loop_with_fake_codex_writes_log_and_stops_done(self) -> None:
        with temp_cwd() as repo:
            git_init(repo)
            fake_codex = repo / "fake-codex"
            fake_codex.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                "Path('changed.txt').write_text('changed', encoding='utf-8')\n"
                "Path('.looop/progress.md').write_text('complete\\nLOOOP_DONE\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            fake_codex.chmod(fake_codex.stat().st_mode | stat.S_IXUSR)

            results = core.run_loop(
                core.RunConfig(
                    max_iterations=3,
                    codex_bin=str(fake_codex),
                )
            )

            self.assertEqual(len(results), 1)
            self.assertTrue(results[0].changed)
            self.assertTrue(results[0].done)
            self.assertEqual(results[0].stop_reason, DONE_MARKER)
            self.assertTrue((repo / ".looop/logs/iteration-1.log").is_file())


if __name__ == "__main__":
    unittest.main()
