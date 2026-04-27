"""Default prompt and progress templates for Looop."""

DONE_MARKER = "LOOOP_DONE"

DEFAULT_PROMPT = """# Looop iteration prompt

You are Codex running inside an iterative coding loop managed by Looop.

Your job in this iteration is to complete exactly one small, useful, incomplete task.

Required workflow:

1. Inspect the repository before changing anything.
2. Read `.looop/progress.md` and use it as the persistent state for the loop.
3. If present, also read `TODO.md`, `PLAN.md`, `PRD.md`, and `README.md`.
4. Pick exactly one small incomplete task that moves the repository forward.
5. Implement only that task. Avoid unrelated rewrites, broad refactors, formatting churn, and speculative cleanup.
6. Run relevant tests or checks when they are available and practical.
7. Update `.looop/progress.md` with:
   - what task you chose
   - what you changed
   - what checks you ran and their result
   - any useful notes for the next iteration
8. Write `LOOOP_DONE` in `.looop/progress.md` only when all known work is complete.

If there is no clear remaining work, make that explicit in `.looop/progress.md`, include `LOOOP_DONE`, and do not invent unnecessary changes.
"""

DEFAULT_PROGRESS = """# Looop Progress

This file is the persistent handoff between Looop iterations.

Codex should update it after every iteration with:

- the task selected for the iteration
- files changed
- checks run and their result
- remaining work or blockers

Do not add the done marker until all known work is complete.
"""
