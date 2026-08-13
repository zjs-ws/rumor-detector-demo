---
name: continue-rumorbuster
description: Continue the current RumorBuster course-project implementation from the checked-in plan and handoff. Use when the user asks to continue, resume, take over, or implement the next project milestone.
disable-model-invocation: true
---

Continue RumorBuster from the current repository state.

1. Read `CLAUDE.md`, `docs/CLAUDE_HANDOFF.md`, and
   `docs/COURSE_PROJECT_PLAN.md` completely.
2. Inspect the current branch, worktree, recent commits, and existing tests.
   Preserve user changes and do not reset or clean the worktree.
3. Work on the first unfinished milestone in `docs/CLAUDE_HANDOFF.md`.
4. Follow test-driven development: add or update a failing test, implement the
   smallest correct change, then run the focused tests.
5. Keep the public-evidence-first product contract:
   - the fine-tuned model is only an auxiliary signal;
   - missing evidence must never become a confident verdict;
   - fetched and cited URLs must be traceable to current-run tool results;
   - private, future-random, opinion, and non-checkable claims are routed
     separately.
6. Update README and CLAUDE.md when behavior, architecture, configuration, or
   commands change.
7. Before committing, run `/validate-rumorbuster`, inspect the diff, and verify
   that secrets, model weights, datasets, and runtime databases are not tracked.
8. Do not push, merge, rent GPU resources, or publish externally unless the
   user explicitly asks for that action.
