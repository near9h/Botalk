# Contributing to botgroup

Thanks for your interest in contributing! 🎉

This document covers everything you need to send a useful PR.

---

## 1. Code of Conduct

By participating you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).
Please report unacceptable behaviour to the maintainers.

## 2. Ground Rules

- **All changes go through a Pull Request** — direct pushes to `main` are not allowed.
- **CI must be green** before merge: backend pytest + ruff + bandit + pip-audit,
  frontend `tsc --noEmit` (see `.github/workflows/ci.yml`).
- **One concern per PR** — split unrelated changes into separate PRs.
- **No secrets in commits** — never commit `.env`, real API keys, or production
  data. See [SECURITY.md](SECURITY.md).

## 3. Development Setup

```bash
git clone <your-fork-url>
cd botgroup

cp .env.example .env       # fill your own NewAPI URL + key

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
pytest -q                  # make sure tests pass before touching anything

# Frontend
cd ../frontend
npm ci
npm run dev                # http://localhost:3000
```

Backend runs on `:8000`, frontend on `:3000`. The production setup uses
Nginx as a single-port reverse proxy on `:3500` — only needed for
end-to-end checks.

## 4. Coding Style

### Backend (Python 3.11+)

- Follow PEP 8; **ruff** is the source of truth (run `ruff check backend/`).
- **Type hints** are mandatory on every public function.
- Module-level docstrings must list `Surface area:` (routes, public classes,
  public functions) — see `backend/app/api/auth.py` for the template.
- Pydantic schemas live in the route file that uses them, **not** in
  `schemas.py`, so each module is readable on its own.

### Frontend (TypeScript)

- `strict: true`. Run `./node_modules/.bin/tsc --noEmit` before pushing.
- Components are functional; props use TS interfaces, no `any`.
- Long-lived components in `frontend/components/`, route-specific
  components in `frontend/app/<route>/`.

### Commit messages

Conventional Commits:

```
<type>(<scope>): <subject>
```

`type` ∈ `feat | fix | refactor | docs | test | chore`
`scope` ∈ `chat | kb | auth | bots | ci | …`

BREAKING changes get a `BREAKING:` line in the body.

## 5. Tests

- **Unit**: `pytest -q` from `backend/`. Add a test next to the feature.
- **E2E**: smoke script in `.trae/documents/09-operations/smoke-test.md`.
- New endpoints must include happy-path + 4xx cases.

## 6. Documentation

Anything user-visible (new route, new env var, new behaviour) **must**
update:

- The endpoint table in `.trae/documents/05-design/README.md`
- The relevant submodule README (e.g. `backend/app/api/kb.py` docstring)
- A line in the implementation index if it adds a feature
  (`.trae/documents/06-implementation/README.md`)

Architecture-changing PRs need an ADR under `.trae/documents/adr/`.

## 7. Review Process

1. Open PR against `main` with a clear title + description.
2. CI runs automatically.
3. A maintainer reviews within ~3 working days.
4. Squash-merge once approved and green.

## 8. Reporting Bugs

Use the [Bug Report template](.github/ISSUE_TEMPLATE/bug_report.md).
Include: botgroup version (`git describe`), model, repro steps, expected vs
actual behaviour, screenshots if relevant.

## 9. Suggesting Features

Use the [Feature Request template](.github/ISSUE_TEMPLATE/feature_request.md).
Tell us the **why** first; the how can be negotiated.

---

Happy hacking 🚀