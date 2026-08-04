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

# Governing Docs

Adhere to these when writing code — not just background reading:

- `docs/scope.md` — what's in/out of scope
- `docs/tech-stack.md` — the stack and why
- `docs/testing-strategy.md` — what to test, how, and CI-passing definition
- `docs/clean-code-enforcement.md` — lint/type/format gates

# Commit History

Reviewers read commit history, not just the final diff — it should show process, concisely.

- One logical change per commit.
- Every commit should build/pass tests; no "wip" or giant dump commits.
- Imperative mood titles ("Add scope.md", not "Added").

# Software Factory Agents

`.claude/agents/`: `backend-implementor` (backend/ only, incl. all backend test suites),
`frontend-implementor` (frontend/ only), `po-verifier` (read-only acceptance gate, runs last).
The main session orchestrates — no orchestrator agent. Each agent has hard file boundaries;
check its frontmatter before assuming it can touch a file. Tests are written by the
implementor that owns the code (per docs/testing-strategy.md) — there is deliberately no
separate test-writer agent. Mark small visual/copy tasks `LIGHT` in the prompt: implementor
does build + spot-check only, no po-verifier gate. Full gates for logic/state/contract
changes and merges. Parallel implementors get different uvicorn ports (8001/8002/…).

# Branching

Multiple agents work independent features in parallel — `staging` is the integration branch that catches conflicts before `main`.

- `feature/<description>` branches off `staging`, one per doc/feature slice.
- Merge feature branches to `staging` via PR, squash merge.
- Periodically merge `staging` to `main` once it's green (builds, tests pass).
