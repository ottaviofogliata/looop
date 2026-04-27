# Looop

Looop is a lightweight autonomous coding loop for Codex: it picks one task, implements it, updates progress, and repeats until done.

`looop` is a small orchestration wrapper around the local OpenAI Codex CLI. It does not implement its own AI agent and it does not call the OpenAI API directly. Instead, it repeatedly runs:

```bash
codex exec "<prompt>"
```

The package installs two equivalent terminal commands:

```bash
looop
lp
```

`lp` is the shorter alias for `looop`. Both commands use the same entry point and support the same subcommands.

## Why It Exists

Codex CLI can already execute a prompt non-interactively. Looop adds a thin, inspectable loop around that capability so a repository can keep moving through small, reviewable iterations:

- initialize a persistent `.looop/` workspace
- ask Codex to choose exactly one small task
- save logs for each iteration
- stop when progress contains `LOOOP_DONE`

## Requirements

- Python 3.10 or newer
- Git
- OpenAI Codex CLI available as `codex`, or a custom path passed with `--codex-bin`

No Python runtime dependencies are required.

## Installation

After cloning the repository, install the CLI with the active Python interpreter:

```bash
git clone <repo-url>
cd looop
make install

looop --help
lp --help
```

`make install` copies the package to `${PREFIX:-~/.local}/share/looop` and installs the `looop` and `lp` launchers into a `PATH` directory where both names resolve correctly. Set `LOOOP_BIN_DIR=/path/to/bin` if you want to choose the launcher directory explicitly.

Uninstall it with:

```bash
make uninstall
```

## Quickstart In Another Repository

```bash
cd ~/Sites/my-project

looop init

# The iteration prompt lives here. Edit it before running if you want
# repository-specific behavior.
$EDITOR .looop/prompt.md

echo "- [ ] Add a healthcheck command" > TODO.md

looop run --max-iterations 5

# The short alias is equivalent:
# lp init
# lp run --max-iterations 5
```

## Commands

Running either command without a subcommand prints help:

```bash
looop
lp
```

Initialize Looop files in the current git repository:

```bash
looop init
looop init --force

lp init
lp init --force
```

Run the loop:

```bash
looop run --max-iterations 5
lp run --max-iterations 5
```

Inspect current status:

```bash
looop status
lp status
```

Delete local iteration logs:

```bash
looop clean
looop clean --yes

lp clean
lp clean --yes
```

Without `--yes`, Looop asks for confirmation before deleting `.looop/logs/`.

## Run Options

`looop run` and `lp run` support:

```bash
--max-iterations <number>
--codex-bin <path-or-name>
--codex-args <args>
--stop-on-no-changes / --no-stop-on-no-changes
--prompt-file <path>
--progress-file <path>
--log-dir <path>
--dry-run
```

Useful examples:

```bash
looop run --codex-args "--model gpt-5.1-codex-max"
looop run --codex-args "--config model_reasoning_effort=high"
looop run --codex-args "--config service_tier=fast"
looop status
looop clean --yes

lp run --codex-args "--model gpt-5.1-codex-max"
lp run --codex-args "--config model_reasoning_effort=high"
lp run --codex-args "--config service_tier=fast"
lp status
lp clean --yes
```

Defaults:

```text
max iterations: 20
codex bin: codex
Codex model: gpt-5.5
Codex reasoning effort: xhigh
Codex service tier: Codex default/user config
stop on no changes: true
prompt file: .looop/prompt.md
progress file: .looop/progress.md
log dir: .looop/logs
```

By default, Looop invokes Codex as if these Codex options were present:

```bash
--model gpt-5.5 --config model_reasoning_effort=xhigh
```

Use `--codex-args` to override any of these defaults or to pass an explicit Codex service tier such as `--config service_tier=fast`.

## The `.looop/` Directory

`looop init` creates:

```text
.looop/
  prompt.md
  progress.md
  logs/
```

Existing `prompt.md` and `progress.md` files are preserved unless `--force` is passed.

### `.looop/prompt.md`

This is the prompt Looop passes to `codex exec` on each iteration. It is the main place to tell Codex how the loop should behave in this repository.

Create it with:

```bash
looop init
```

Then edit it in the repository where Looop will run:

```bash
$EDITOR .looop/prompt.md
```

You usually do not pass the iteration prompt on the command line. Looop reads `.looop/prompt.md`, passes its full content to `codex exec`, waits for Codex to finish, then reads the same file again before the next iteration.

Use the prompt file for durable instructions such as:

- which planning files Codex should inspect
- what kind of task Codex should choose
- how large each iteration should be
- which checks Codex should run
- how Codex should update `.looop/progress.md`
- when Codex is allowed to write `LOOOP_DONE`

A minimal repository-specific prompt can look like this:

```markdown
# Looop iteration prompt

Read `.looop/progress.md`, `TODO.md`, and `README.md`.
Pick exactly one small incomplete task.
Implement only that task.
Run the most relevant check available in this repository.
Update `.looop/progress.md` with the task, changed files, checks, and remaining work.
Only write `LOOOP_DONE` when all known work is complete.
```

To use a different prompt file for one run, pass `--prompt-file`:

```bash
looop run --prompt-file docs/looop-prompt.md
```

The default prompt path, `.looop/prompt.md`, is resolved at the git repository root. A custom relative `--prompt-file` path is resolved from the current working directory.

### `.looop/progress.md`

This file is the persistent handoff between iterations. Codex updates it after each run with the selected task, changed files, check results, remaining work, and notes for the next iteration.

The progress file is state, not the main instruction prompt. Put long-running behavior instructions in `.looop/prompt.md`; put iteration results and remaining work in `.looop/progress.md`.

The loop stops when the progress file contains this marker text:

```text
LOOOP_DONE
```

Do not include `LOOOP_DONE` anywhere in `.looop/progress.md` unless you want the loop to stop.

## Stop Conditions

Looop stops before running Codex when `.looop/progress.md` already contains `LOOOP_DONE`.

After each iteration, Looop stops when the first matching runtime condition applies:

- Codex exits with a non-zero status.
- `--stop-on-no-changes` is enabled and the iteration leaves no worktree changes.
- `.looop/progress.md` contains `LOOOP_DONE`.
- `--max-iterations` has been reached.

`--stop-on-no-changes` is enabled by default. The no-change check compares the git worktree before and after an iteration, including tracked files and non-ignored untracked files, while ignoring files under the configured log directory.

`--max-iterations` is a safety limit, not a completion signal. If the loop reaches the limit without `LOOOP_DONE`, there may still be remaining work in `.looop/progress.md`.

## Git Behavior

`looop run` verifies that it is inside a git repository. If the working tree already has uncommitted changes, Looop warns before starting. It never commits, stashes, resets, or discards user changes.

If there are no changes, the default `--stop-on-no-changes` behavior stops the loop.

## Logging

Each iteration writes a local log file:

```text
.looop/logs/iteration-1.log
.looop/logs/iteration-2.log
.looop/logs/iteration-3.log
```

Logs include the timestamp, iteration number, Codex command, Codex stdout and stderr, and the final iteration result. Runtime logs are local artifacts and are ignored by the package's repository `.gitignore`.

## Safety Notes

- Looop runs local commands in your repository.
- Codex execution is delegated to the installed Codex CLI.
- Looop does not make network calls itself.
- Looop does not call the OpenAI API directly.
- Looop does not commit, stash, reset, or discard changes.

## Development

Run tests:

```bash
make test
```

Run static checks:

```bash
make lint
```

Remove local build and cache artifacts:

```bash
make clean
```

## Example Workflow

```bash
cd ~/Sites/my-project
looop init
echo "- [ ] Add a healthcheck command" > TODO.md
looop run --max-iterations 5
looop status
```

Using the alias:

```bash
cd ~/Sites/my-project
lp init
echo "- [ ] Add a healthcheck command" > TODO.md
lp run --max-iterations 5
lp status
```
