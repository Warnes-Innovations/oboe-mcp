<!--
Copyright (C) 2026 Gregory R. Warnes
SPDX-License-Identifier: AGPL-3.0-or-later

This file is part of Oboe MCP.
For commercial licensing, contact greg@warnes-innovations.com
-->

# Contributing to oboe-mcp

Thanks for your interest in the project. This document covers the things that
reading the code will not tell you: which branch to target, how to run the
checks, and where the confirmation boundaries are.

## Branch model

The default branch is **`devel`**. `main` is the released branch and is
protected.

```
feature branch ──PR──> devel ──PR──> main ──> PyPI release
```

- **Open pull requests against `devel`**, not `main`. A PR opened against
  `main` targets the released branch and will be asked to retarget.
- Branch names follow the change type: `feat/…`, `fix/…`, `chore/…`,
  `docs/…`.
- Promotion from `devel` to `main` is its own pull request, made when the work
  on `devel` is ready to be released.
- Publishing to PyPI happens from `main` after that promotion. It is a
  separate, deliberately gated step — see *Releases* below.

For anything beyond a small single-file edit, work in a linked worktree under
`worktrees/` rather than in the primary checkout:

```bash
git worktree add worktrees/my-change -b feat/my-change origin/devel
```

That directory is gitignored. Working directly in the shared checkout has
twice caused commits to land on the wrong branch or to sweep up another
session's files.

## Development setup

Requires Python 3.11 or newer. The project uses [uv](https://docs.astral.sh/uv/)
and `hatchling`.

```bash
uv sync
```

## Running the tests

The full suite:

```bash
uv run pytest tests/ -q
```

Redirect to a file rather than piping when the output matters, so it can be
re-examined:

```bash
uv run pytest tests/ -q > tmp/test.out 2>&1; tail -30 tmp/test.out
```

`tests/test_concurrency.py` spawns real subprocesses — it is testing
cross-process file locking, which threads cannot exercise. It is slower than
the rest of the suite for that reason. Do not convert it to threads.

**All tests must pass before a PR is merged**, including tests unrelated to
your change. If you find a pre-existing failure, say so in the PR rather than
working around it.

## Expectations for a change

- **Fix the bug class, not just the instance.** After correcting a defect,
  grep the tree for the same pattern and fix every occurrence in the same
  change. State the grep and its result in the PR — including when it comes
  back clean.
- **Add a regression test for every reported bug.** Reproduce the failure
  first, then fix it, so the test is known to detect the thing it guards.
- **A test that has never failed has not been validated.** Where practical,
  confirm a new test fails against the unfixed code before relying on it.
- **Source files carry the copyright and SPDX header.** See any file in
  `src/oboe_mcp/` for the form. Preserve a shebang on line 1 and place the
  header immediately after.
- **Bound new dependencies on both sides** (`foo>=1.0,<2`, not `foo>=1.0`). A
  lockfile pins transitive versions but cannot validate a declaration, so an
  unbounded dependency lets a new major release break the package while every
  existing test still passes.

## Concurrency

Session state is shared between the MCP server, `oboe-cli`, and any other
process pointed at the same project. Reads and writes go through the lock and
atomic-write helpers in `src/oboe_mcp/locking.py`.

If you add a code path that touches session files:

- Use `session_transaction()` for read-modify-write cycles rather than pairing
  `load_session` with `save_session` by hand.
- Never write a session file or `index.json` with a plain `open(..., "w")` —
  that truncates the file in place, and a concurrent reader will see a partial
  document.

See the *Concurrency* section of `README.md` for the guarantees this provides
to callers.

## Releases

Releases are cut from `main` and published to PyPI by the `publish.yml`
workflow using Trusted Publishing.

Each of the following is an irreversible step and requires explicit
confirmation from the maintainer at the time it happens, even if publishing
was already requested in general terms:

- `git push`
- tag creation
- GitHub release creation
- PyPI publication

Version numbers follow semantic versioning. **Two files carry the version and
must be updated together** — `pyproject.toml` (`version`) and
`src/oboe_mcp/__init__.py` (`__version__`). They have drifted before: 0.2.0
shipped reporting `__version__ == "0.1.2"`. Update `CHANGELOG.md` in the same
change as the bump.

### Verify the artifact before tagging — always

A PyPI version number is immutable and cannot be reused; a broken `X.Y.Z` means
shipping `X.Y.Z+1`. Build and exercise the real artifact first:

```bash
uv build --out-dir dist/
uv run --isolated --no-project \
  --with ./dist/oboe_mcp-<VERSION>-py3-none-any.whl --with 'mcp<3.0' \
  oboe-mcp --help
```

Smoke-test both entry points (`oboe-mcp`, `oboe-cli`) **and any command the
release notes tell users to run**. The 0.3.0 changelog advertised
`uvx oboe-mcp migrate` while no such command existed — running the advertised
command against a clean install is what catches that.

### TestPyPI dry run — only when `publish.yml` changed

```bash
gh workflow run publish.yml --ref main -f repository=testpypi
```

Run this **only when `.github/workflows/publish.yml` has changed since the last
release**. It validates the CI publish path — build job, artifact hand-off,
action pins, permissions — and nothing else.

It specifically does **not** validate PyPI's trusted publisher configuration:
TestPyPI needs a separate registration, and a failure there says nothing about
PyPI. On 2026-07-31 a dry run failed with `invalid-publisher` while PyPI's
config was intact and the real publish succeeded unchanged.

Running it every time would spend real effort on a step that usually reports
nothing — and a check that habitually says nothing is one people learn to skip
at exactly the moment it would have mattered.

## Reporting a security issue

Please do **not** open a public issue for a security vulnerability. Report it
privately to greg@warnes-innovations.com.

This repository has no `SECURITY.md` at present; the address above is the
maintainer contact listed in `pyproject.toml`.

## Licensing

This project is licensed under **AGPL-3.0-or-later**. By contributing, you
agree that your contribution is licensed under those same terms.

There is currently no separate CLA or DCO sign-off requirement. Commercial
licensing is available — contact greg@warnes-innovations.com.
