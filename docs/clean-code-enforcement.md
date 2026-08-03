# Clean Code Enforcement Plan

| Layer | Concern | Tool |
|---|---|---|
| Backend | Lint + format | Ruff |
| Backend | Types | Pyright |
| Backend | Docstring presence | Ruff `D` rules (pydocstyle) — enforces a docstring exists, not Google-style content |
| Frontend | Lint + format | ESLint + Prettier |
| Frontend | Types | `tsc --noEmit` |

## Two enforcement points

- **Pre-commit hooks** (`pre-commit` framework) — fast local feedback before a commit is even made.
- **CI** — the actual gate, since pre-commit is skippable locally (`--no-verify`). Extends testing-strategy.md's CI-passing list with `eslint`, `tsc --noEmit`, `prettier --check`.

## Branch protection

Require the CI status check to pass before merge into `staging`/`main`. Without this, "every commit should build/pass tests" (CLAUDE.md) is a hope, not an enforced rule.

## Explicitly deferred

- Cyclomatic complexity / function-length limits
- Dependency vulnerability scanning (pip-audit, npm audit)

Reasonable for a long-lived project, not worth the setup time in this timebox.
