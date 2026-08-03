# Principles

- Value code maintainability for the next person who will inherit it.
- Deterministically enforce code quality standards where possible.
- Be concise — in code, docs, commit messages, and PRs.
- Deferring a component is fine, but it must be addressed in `docs/scope.md`.

# Deliverables

1. The application
2. `DECISIONS.md`
3. `README.md`

# File Conventions

- Deliverables and reference docs (`README.md`, `DECISIONS.md`, `BRIEF.md`) live at repo top level, UPPERCASE.
- Intermediate outputs (scope, tech stack, testing strategy, clean code enforcement plan) live under `docs/`, lowercase filenames.

# Commit History

Reviewers read commit history, not just the final diff — it should show process, concisely.

- One logical change per commit.
- Every commit should build/pass tests; no "wip" or giant dump commits.
- Imperative mood titles ("Add scope.md", not "Added").

# Branching

Multiple agents work independent features in parallel — `staging` is the integration branch that catches conflicts before `main`.

- `feature/<description>` branches off `staging`, one per doc/feature slice.
- Merge feature branches to `staging` via PR, squash merge.
- Periodically merge `staging` to `main` once it's green (builds, tests pass).
