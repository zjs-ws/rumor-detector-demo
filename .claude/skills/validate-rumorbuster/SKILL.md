---
name: validate-rumorbuster
description: Run the appropriate RumorBuster validation checks before a commit, handoff, demo, or release.
disable-model-invocation: true
---

Validate the repository without exposing secrets.

1. Run `git diff --check` and inspect `git status --short`.
2. Confirm `.env`, `.claude/deepseek.env`, `config.yaml`, `runtime/`, model
   weights, and raw datasets are not tracked.
3. Run the narrowest relevant tests first.
4. For backend changes, run the matching pytest files in Docker when Docker is
   available. If Docker is unavailable, report that limitation rather than
   claiming the tests passed.
5. For frontend changes, run:

   ```bash
   corepack pnpm --dir frontend typecheck
   ```

6. For Compose or deployment changes, run:

   ```bash
   docker compose config -q
   ```

7. Review the final diff for unsupported capability claims, fabricated
   citations, hardcoded secrets, fixed fake confidence scores, and destructive
   commands.
8. Summarize what passed, what was skipped, and any remaining risk.
