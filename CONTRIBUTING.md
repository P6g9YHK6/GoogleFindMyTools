# Contributing

Thanks for considering a contribution. This is a small project maintained
on a best-effort basis - a few things that keep review fast for both of us.

## Before you start

For anything beyond a small fix (a new feature, a behavior change, a new
config option), open an issue first describing what you want to do and why.
Saves you writing code that doesn't land because the approach didn't fit.

## Setting up

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-web.txt -r requirements-dev.txt
```

Run the web app locally with `uvicorn webui.main:app --reload`, or build the
whole Docker image with `docker compose -f docker-compose.dev.yml up --build`.

## Updating dependencies

`requirements.txt`/`requirements-web.txt` are the source of truth (loose,
human-edited version constraints) - CI installs from these directly, so
they're what actually gets exercised against whatever's newest on PyPI.
`requirements.lock` is a fully pinned, hash-checked resolution of both,
regenerated with [uv](https://github.com/astral-sh/uv):

```
uv pip compile requirements.txt requirements-web.txt -o requirements.lock --python-version 3.11 --generate-hashes
```

Only the Docker image build installs from `requirements.lock` (see
`docker/web/Dockerfile`), so a rebuild of the same commit always gets the
same dependency versions instead of whatever's newest that day. Regenerate
it whenever you change either `requirements*.txt` file, and commit the
result in the same PR.

## Before opening a PR

```
ruff check .
pytest
```

Both run in CI (see `.github/workflows/test.yml`) and a PR that fails either
won't get merged. There's also a `.pre-commit-config.yaml` if you'd rather
catch lint issues before you commit than after you push:

```
pip install pre-commit
pre-commit install
```

## Code style

- Match the surrounding code: this codebase favors longer explanatory
  comments over terse ones, especially anywhere the "why" isn't obvious from
  the diff alone (a past bug, a platform quirk, a deliberate tradeoff).
  `ruff` enforces the mechanical stuff; it won't tell you to write those.
- Add tests for new behavior. Look at the existing tests under `tests/` for
  the mocking patterns already in use (`tests/conftest.py` explains the
  "patch where it's looked up" rule that most of them rely on).
- Keep commits focused - one logical change per commit, with a message that
  explains why, not just what changed line-by-line.

## Reporting bugs

Open an issue with what you did, what you expected, what happened instead,
and (if it's a web UI issue) the relevant section of the System Log or
Forwarding Log. For anything security-sensitive, see `SECURITY.md` instead
of opening a public issue.
